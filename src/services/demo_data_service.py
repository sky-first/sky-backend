"""Dados de demonstração, ligados e desligados a partir das Definições.

Porque existe
-------------
Até aqui, dar dados de demonstração a um cliente era correr um Job de
Kubernetes à mão — com o SHA da imagem copiado do GitOps, o `securityContext`
certo para o Kyverno passar, e um email de dono que tinha de existir naquela
base. Três coisas para acertar, e cada uma delas falhou pelo menos uma vez.

Pior: o dono das ligações acabava por ser quem o Job dissesse, e não quem
precisava delas. Ficavam de `rbac.owner@example.com`, um utilizador de
semente que ninguém usa e que, se algum dia for apagado, leva as ligações
atrás (``created_by`` tem ``ON DELETE CASCADE``).

Aqui, **quem liga é quem fica dono**. Não há terceiro nome a decidir.

O que isto NÃO faz
------------------
Não copia dados. As ligações apontam para a mesma base de demonstração que a
demo pública sempre usou; o que fica na base do cliente são as linhas que
dizem que a ligação existe e a quem pertence. Ligar isto em dez clientes não
duplica um único registo.

Reversível: `desligar()` apaga o que `ligar()` criou, e nada mais.
"""

from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.models.connection import DataConnection
from src.models.space import Space, SpaceConnection, SpaceMember
from src.models.user import User
from src.utils.encryption import encrypt_dict

logger = logging.getLogger(__name__)

#: O nome do espaço criado. Fixo de propósito: é por ele que se reconhece o
#: que veio daqui, e é o que `desligar()` procura.
NOME_DO_ESPACO = "Dados de demonstração"

#: As cinco ligações, uma por esquema de negócio. A mesma lista que o
#: `scripts/seed_demo_connections.py` usa — se um dia divergirem, o que está
#: no ecrã deixa de bater certo com o que o semeador põe.
LIGACOES: List[Dict[str, str]] = [
    {"nome": "Demo — Sales", "esquema": "crm"},
    {"nome": "Demo — Marketing", "esquema": "marketing"},
    {"nome": "Demo — Finance", "esquema": "finance"},
    {"nome": "Demo — Web Analytics", "esquema": "web_analytics"},
    {"nome": "Demo — Product Usage", "esquema": "product_usage"},
]


class DemoDataIndisponivel(Exception):
    """A base de demonstração não está configurada neste ambiente."""


def configurada() -> bool:
    """Há credenciais para a base de demonstração?

    Sem elas não há nada a ligar, e o botão não deve sequer aparecer — um
    botão que só sabe dar erro é pior do que nenhum.
    """
    return bool(
        getattr(settings, "DEMO_PG_HOST", "")
        and getattr(settings, "DEMO_PG_USER", "")
        and getattr(settings, "DEMO_PG_PASSWORD", "")
    )


def _config(esquema: str) -> Dict[str, object]:
    return {
        "host": settings.DEMO_PG_HOST,
        "port": int(getattr(settings, "DEMO_PG_PORT", 5432) or 5432),
        "database": getattr(settings, "DEMO_PG_DB", "skydemo") or "skydemo",
        "username": settings.DEMO_PG_USER,
        "password": settings.DEMO_PG_PASSWORD,
        "schema": esquema,
        "ssl_mode": getattr(settings, "DEMO_PG_SSL_MODE", "require") or "require",
    }


async def estado(db: AsyncSession, dono: User) -> Dict[str, object]:
    """Está ligado? Quantas ligações? Serve o interruptor do ecrã."""
    espaco = await _espaco_existente(db, dono)
    if espaco is None:
        return {"ligado": False, "ligacoes": 0, "disponivel": configurada()}
    n = len(await _ligacoes_existentes(db, dono))
    return {"ligado": n > 0, "ligacoes": n, "disponivel": configurada()}


async def _espaco_existente(db: AsyncSession, dono: User) -> Optional[Space]:
    res = await db.execute(
        select(Space).where(Space.name == NOME_DO_ESPACO, Space.created_by == dono.id)
    )
    return res.scalar_one_or_none()


async def _ligacoes_existentes(db: AsyncSession, dono: User) -> List[DataConnection]:
    nomes = [l["nome"] for l in LIGACOES]
    res = await db.execute(
        select(DataConnection).where(
            DataConnection.name.in_(nomes),
            DataConnection.created_by == dono.id,
            DataConnection.deleted_at.is_(None),
        )
    )
    return list(res.scalars().all())


async def ligar(db: AsyncSession, dono: User) -> Dict[str, object]:
    """Cria o espaço e as cinco ligações, com ``dono`` como dono.

    Idempotente: chamar duas vezes não duplica. Quem já tem, fica na mesma.
    """
    if not configurada():
        raise DemoDataIndisponivel("Demo data is not configured for this environment.")

    espaco = await _espaco_existente(db, dono)
    if espaco is None:
        espaco = Space(
            id=uuid.uuid4(),
            name=NOME_DO_ESPACO,
            created_by=dono.id,
            description="Ligações de demonstração — dados fictícios, seguros para mostrar.",
        )
        db.add(espaco)
        await db.flush()
        db.add(SpaceMember(space_id=espaco.id, user_id=dono.id, role="owner"))
        await db.flush()

    existentes = {c.name: c for c in await _ligacoes_existentes(db, dono)}
    criadas: List[uuid.UUID] = []

    for spec in LIGACOES:
        conn = existentes.get(spec["nome"])
        cifrada = encrypt_dict(_config(spec["esquema"]))
        if conn is None:
            conn = DataConnection(
                id=uuid.uuid4(),
                name=spec["nome"],
                connector_id="postgresql",
                description=f"Demo PostgreSQL — schema '{spec['esquema']}'.",
                status="active",
                config=cifrada,
                created_by=dono.id,
                tier="internal",
            )
            db.add(conn)
            await db.flush()
            criadas.append(conn.id)
        else:
            # Re-ligar refresca a configuração: a password da base de
            # demonstração pode ter rodado desde a primeira vez.
            conn.config = cifrada
            conn.status = "active"
            await db.flush()

        ja = await db.execute(
            select(SpaceConnection).where(
                SpaceConnection.space_id == espaco.id,
                SpaceConnection.connection_id == conn.id,
            )
        )
        if ja.scalar_one_or_none() is None:
            db.add(SpaceConnection(space_id=espaco.id, connection_id=conn.id))
            await db.flush()

    # Sem esquema, o projeto não responde a nada.
    #
    # Isto criava as ligações e o `SpaceConnection` e ficava-se por aí: sem
    # metadados e sem `space_tables`. A demonstração aparecia montada — cinco
    # ligações, estado "activo" — e não tinha uma única tabela por trás. No
    # tenant `skyfirstlabs` esteve assim desde sempre.
    #
    # E como a fronteira de dados passa a ser o PROJETO (`space_tables`), esta
    # é também a linha que dá dados ao projeto. Ligar a demonstração e escolher
    # os dados do projeto passam a ser o mesmo gesto.
    tabelas = await _descobrir_tabelas(db, espaco)

    await db.commit()
    logger.info(
        "demo_data_ligado",
        extra={"user": str(dono.id), "novas": len(criadas), "tabelas": tabelas},
    )
    return {
        "ligado": True,
        "ligacoes": len(LIGACOES),
        "novas": len(criadas),
        "tabelas": tabelas,
    }


async def _descobrir_tabelas(db: AsyncSession, espaco: Space) -> int:
    """Lê o esquema de cada ligação do espaço e liga as tabelas ao projeto.

    Idempotente: não duplica `SpaceTable`, e voltar a correr refresca os
    metadados. Uma ligação que falhe não derruba as outras — mas fica no log,
    porque uma demonstração com quatro dos cinco esquemas responde torto e é
    pior de diagnosticar do que uma que não responde de todo.
    """
    from src.connectors.registry import get_connector
    from src.models.connection import ConnectionMetadata
    from src.models.space import SpaceTable
    from src.utils.encryption import decrypt_dict

    ligadas = await db.execute(
        select(DataConnection)
        .join(SpaceConnection, SpaceConnection.connection_id == DataConnection.id)
        .where(SpaceConnection.space_id == espaco.id)
    )

    total = 0
    for conn in ligadas.scalars().all():
        try:
            connector = get_connector(conn.connector_id)
            meta = await connector.get_metadata(decrypt_dict(conn.config, settings.ENCRYPTION_KEY))
        except Exception:
            logger.exception("demo_data_sem_esquema", extra={"ligacao": str(conn.id)})
            continue

        tabelas = [t for t in (meta.get("tables") or []) if t.get("name")]

        linha = (
            await db.execute(
                select(ConnectionMetadata).where(ConnectionMetadata.connection_id == conn.id)
            )
        ).scalar_one_or_none()
        if linha is None:
            db.add(
                ConnectionMetadata(
                    connection_id=conn.id, tables=tabelas, schemas=meta.get("schemas") or []
                )
            )
        else:
            linha.tables = tabelas
            linha.schemas = meta.get("schemas") or []
        await db.flush()

        ja = {
            (r.table_name, r.schema_name)
            for r in (
                await db.execute(
                    select(SpaceTable).where(
                        SpaceTable.space_id == espaco.id,
                        SpaceTable.connection_id == conn.id,
                    )
                )
            )
            .scalars()
            .all()
        }
        for t in tabelas:
            chave = (t["name"], t.get("schema"))
            if chave in ja:
                continue
            db.add(
                SpaceTable(
                    space_id=espaco.id,
                    connection_id=conn.id,
                    table_name=t["name"],
                    schema_name=t.get("schema"),
                )
            )
            total += 1
        await db.flush()

    return total


async def desligar(db: AsyncSession, dono: User) -> Dict[str, object]:
    """Apaga o que ``ligar()`` criou — e nada mais.

    Só toca em ligações com os nomes fixos DESTA lista e criadas por este
    utilizador. Uma ligação que o cliente tenha criado com o mesmo nome não é
    apagada, porque o ``created_by`` não bate certo.
    """
    ligacoes = await _ligacoes_existentes(db, dono)
    for conn in ligacoes:
        await db.execute(
            SpaceConnection.__table__.delete().where(SpaceConnection.connection_id == conn.id)
        )
        await db.delete(conn)

    espaco = await _espaco_existente(db, dono)
    if espaco is not None:
        await db.execute(SpaceMember.__table__.delete().where(SpaceMember.space_id == espaco.id))
        await db.delete(espaco)

    await db.commit()
    logger.info("demo_data_desligado", extra={"user": str(dono.id), "removidas": len(ligacoes)})
    return {"ligado": False, "removidas": len(ligacoes)}
