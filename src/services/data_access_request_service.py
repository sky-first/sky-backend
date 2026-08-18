"""Pedir dados sem poder ver o catálogo — e aprová-los com prazo.

O fluxo, por inteiro:

1. Quem pede escreve em português. Não vê ligações, não vê tabelas.
2. A resposta é **sempre a mesma frase**, haja correspondência ou não.
3. Do lado de quem aprova, a IA traduz o texto numa proposta concreta.
4. Aprovar cria as linhas de `space_tables` do projeto — no modelo novo, dar
   dados a um projeto **é** isso.

As defesas estão anotadas com o número do caso em
``docs/modelo-projeto-equipa-e-pedidos-de-acesso.md`` §6, e cada uma tem teste.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select

from src.models.connection import ConnectionMetadata, DataConnection
from src.models.data_access_request import DataAccessRequest
from src.models.space import SpaceConnection, SpaceTable

logger = logging.getLogger(__name__)


#: A frase que quem pede recebe **sempre**. Se variasse entre "encontrei" e
#: "não encontrei", quem sonda aprendia o catálogo por tentativa e erro sem
#: nunca ter acesso a nada. (S1)
RESPOSTA = "O teu pedido foi enviado."

#: Quantos pedidos uma pessoa pode fazer por dia. Quinhentos pedidos com
#: palavras diferentes mapeiam o negócio pelas aprovações recebidas; o travão
#: torna isso lento e visível. (S3)
LIMITE_DIARIO = 20

#: Prazo por omissão de uma permissão concedida. Acesso sem fim acumula-se para
#: sempre e ninguém volta a olhar. (S5)
PRAZO_OMISSAO_DIAS = 90


class LimiteDePedidos(Exception):
    """Passou do limite diário. A mensagem para quem pede não muda."""


class PedidoInvalido(Exception):
    """Falta o prazo, ou a decisão não faz sentido."""


# ── Quem aprova ──────────────────────────────────────────────────────────────


async def dono_dos_dados(db, connection_id: UUID) -> Optional[UUID]:
    """Quem decide sobre esta ligação.

    Hoje devolve o dono explícito, se existir, e senão ``None`` — que o
    chamador lê como "o admin do cliente". O campo existe desde já para que
    passar a um dono por ligação seja configuração, e não migração.
    """
    conn = (
        await db.execute(select(DataConnection).where(DataConnection.id == connection_id))
    ).scalar_one_or_none()
    if conn is None:
        return None
    return getattr(conn, "data_owner_user_id", None)


# ── Pedir ────────────────────────────────────────────────────────────────────


async def criar(db, *, requester_id: UUID, space_id: UUID, texto: str) -> str:
    """Grava o pedido e devolve **sempre** a mesma frase.

    Não faz o mapeamento aqui de propósito: se a IA corresse em linha, o tempo
    de resposta passava a dizer se houve correspondência, e a latência tornava-se
    o oráculo que a frase fixa evita. (S2)
    """
    texto = (texto or "").strip()
    if not texto:
        raise PedidoInvalido("O pedido não pode ser vazio.")

    desde = datetime.now(timezone.utc) - timedelta(days=1)
    feitos = (
        await db.execute(
            select(func.count())
            .select_from(DataAccessRequest)
            .where(
                DataAccessRequest.requester_user_id == requester_id,
                DataAccessRequest.created_at >= desde,
            )
        )
    ).scalar_one()
    if feitos >= LIMITE_DIARIO:
        raise LimiteDePedidos(RESPOSTA)

    db.add(
        DataAccessRequest(
            requester_user_id=requester_id,
            space_id=space_id,
            texto=texto[:4000],
            status="pending",
        )
    )
    await db.flush()
    return RESPOSTA


# ── Traduzir, do lado de quem aprova ─────────────────────────────────────────

#: Palavras que não ajudam a distinguir uma tabela de outra.
_VAZIAS = {
    "de",
    "do",
    "da",
    "dos",
    "das",
    "o",
    "a",
    "os",
    "as",
    "para",
    "com",
    "em",
    "preciso",
    "queria",
    "quero",
    "gostava",
    "dados",
    "informacao",
    "informação",
    "the",
    "of",
    "i",
    "need",
    "want",
    "data",
    "please",
    "por",
    "favor",
}


def _palavras(texto: str) -> List[str]:
    cru = re.findall(r"[\wÀ-ÿ]+", (texto or "").lower())
    return [p for p in cru if len(p) > 2 and p not in _VAZIAS]


def _pontuar(palavras: Sequence[str], alvo: str) -> int:
    alvo = (alvo or "").lower()
    return sum(1 for p in palavras if p in alvo or alvo in p)


async def propor(db, pedido: DataAccessRequest) -> List[Dict[str, Any]]:
    """Traduz o texto do pedido em tabelas candidatas **do projeto para fora**.

    Corre com a visibilidade de quem aprova — nunca com a de quem pede — e a
    saída é uma **estrutura fechada**: lista de tabelas com um motivo. O texto
    do requerente entra aqui como dado; nada nele pode virar instrução, porque
    nada nele é interpolado num prompt que produza texto livre. (S4)

    Implementação determinística, no espírito do gerador de fórmulas: cruza as
    palavras do pedido com os nomes de esquema, tabela e ligação que o cliente
    tem. Um gerador por LLM entra depois por cima, com a mesma assinatura e a
    mesma estrutura de saída.
    """
    palavras = _palavras(pedido.texto)
    if not palavras:
        return []

    linhas = (
        await db.execute(
            select(DataConnection, ConnectionMetadata)
            .join(ConnectionMetadata, ConnectionMetadata.connection_id == DataConnection.id)
            .where(DataConnection.deleted_at.is_(None))
        )
    ).all()

    ja_no_projeto = {
        (r.connection_id, r.table_name, r.schema_name)
        for r in (
            await db.execute(select(SpaceTable).where(SpaceTable.space_id == pedido.space_id))
        )
        .scalars()
        .all()
    }

    candidatas: List[Dict[str, Any]] = []
    for conn, meta in linhas:
        for t in meta.tables or []:
            nome = (t.get("name") or "").strip()
            if not nome:
                continue
            esquema = t.get("schema")
            if (conn.id, nome, esquema) in ja_no_projeto:
                continue  # o projeto já tem esta
            pontos = (
                _pontuar(palavras, nome) * 3
                + _pontuar(palavras, esquema or "") * 2
                + _pontuar(palavras, conn.name or "")
            )
            if pontos <= 0:
                continue
            candidatas.append(
                {
                    "connection_id": str(conn.id),
                    "connection_name": conn.name,
                    "schema_name": esquema,
                    "table_name": nome,
                    "pontos": pontos,
                    "motivo": f"o pedido fala de {', '.join(sorted(set(palavras))[:4])}",
                }
            )

    candidatas.sort(key=lambda c: (-c["pontos"], c["table_name"]))
    proposta = candidatas[:10]

    pedido.proposta = proposta
    pedido.status = "proposed"
    await db.flush()
    return proposta


# ── Decidir ──────────────────────────────────────────────────────────────────


async def aprovar(
    db,
    pedido: DataAccessRequest,
    *,
    aprovador_id: UUID,
    tabelas: Optional[List[Dict[str, Any]]] = None,
    prazo_dias: Optional[int] = None,
    motivo: str = "",
) -> int:
    """Dá as tabelas ao **projeto** do pedido, com prazo.

    ``tabelas`` deixa o aprovador cortar a proposta — o que a IA sugeriu não é
    o que fica, é o que se propõe. Sem ``tabelas``, vale a proposta inteira.
    """
    if pedido.status in ("approved", "rejected", "expired"):
        raise PedidoInvalido("Este pedido já foi decidido.")

    escolhidas = tabelas if tabelas is not None else (pedido.proposta or [])
    if not escolhidas:
        raise PedidoInvalido("Não há tabelas para conceder.")

    dias = prazo_dias if prazo_dias is not None else PRAZO_OMISSAO_DIAS
    if dias <= 0:
        # Sem prazo não se aprova: é o que limita o estrago de um carimbo
        # distraído. (S5)
        raise PedidoInvalido("Uma permissão tem de ter prazo.")

    ja = {
        (str(r.connection_id), r.table_name, r.schema_name)
        for r in (
            await db.execute(select(SpaceTable).where(SpaceTable.space_id == pedido.space_id))
        )
        .scalars()
        .all()
    }

    novas = 0
    for t in escolhidas:
        chave = (str(t["connection_id"]), t["table_name"], t.get("schema_name"))
        if chave in ja:
            continue
        db.add(
            SpaceTable(
                space_id=pedido.space_id,
                connection_id=UUID(str(t["connection_id"])),
                table_name=t["table_name"],
                schema_name=t.get("schema_name"),
            )
        )
        # A ligação passa a estar no projeto — senão o projeto tem tabelas de
        # uma fonte que não conhece.
        existe = (
            await db.execute(
                select(SpaceConnection).where(
                    SpaceConnection.space_id == pedido.space_id,
                    SpaceConnection.connection_id == UUID(str(t["connection_id"])),
                )
            )
        ).scalar_one_or_none()
        if existe is None:
            db.add(
                SpaceConnection(
                    space_id=pedido.space_id,
                    connection_id=UUID(str(t["connection_id"])),
                )
            )
        novas += 1

    pedido.status = "approved"
    pedido.decided_by_user_id = aprovador_id
    pedido.decided_at = datetime.now(timezone.utc)
    pedido.motivo_decisao = motivo or None
    pedido.expires_at = datetime.now(timezone.utc) + timedelta(days=dias)
    await db.flush()

    logger.info(
        "pedido_de_acesso_aprovado",
        extra={
            "pedido": str(pedido.id),
            "projeto": str(pedido.space_id),
            "tabelas": novas,
            "prazo_dias": dias,
        },
    )
    return novas


async def recusar(db, pedido: DataAccessRequest, *, aprovador_id: UUID, motivo: str = "") -> None:
    if pedido.status in ("approved", "rejected", "expired"):
        raise PedidoInvalido("Este pedido já foi decidido.")
    pedido.status = "rejected"
    pedido.decided_by_user_id = aprovador_id
    pedido.decided_at = datetime.now(timezone.utc)
    pedido.motivo_decisao = motivo or None
    await db.flush()
