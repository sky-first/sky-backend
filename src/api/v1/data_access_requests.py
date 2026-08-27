"""Pedir dados, e decidir sobre pedidos.

Duas superfícies bem separadas, e a separação é a segurança:

* **quem pede** só tem `POST /access-requests` e só recebe uma frase;
* **quem aprova** vê a lista, a proposta e o texto original.

Nada do lado de quem pede devolve nomes de tabelas, contagens ou sequer se
houve correspondência — ver ``docs/modelo-projeto-equipa-e-pedidos-de-acesso.md``
§6, casos S1 a S5.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.permissions import is_tenant_admin
from src.models.data_access_request import DataAccessRequest
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.services import data_access_request_service as pedidos

logger = logging.getLogger(__name__)
router = APIRouter()


class PedidoNovo(BaseModel):
    space_id: UUID = Field(..., description="O projeto que precisa dos dados.")
    texto: str = Field(..., min_length=3, max_length=4000)


class Recibo(BaseModel):
    """Tudo o que quem pede recebe. De propósito: uma frase e nada mais."""

    mensagem: str


class Decisao(BaseModel):
    tabelas: Optional[List[Dict[str, Any]]] = Field(
        None, description="Subconjunto da proposta. Vazio/ausente = a proposta toda."
    )
    prazo_dias: Optional[int] = Field(None, ge=1, le=3650)
    motivo: str = ""


async def _pertence_ao_projeto(db: AsyncSession, user: User, space_id: UUID) -> bool:
    """Alcança este projeto — **por qualquer via**.

    Olhava só para `space_members` e para quem criou o projeto. Com o modelo
    de 26/08 isso deixou de chegar: quem é convidado entra pela equipa
    **Geral**, e quem vem por uma equipa da empresa nunca teve linha em
    `space_members`.

    O efeito era do pior tipo. Esta função guarda a criação de um pedido de
    dados, e quando diz «não» a resposta é **a mesma de sempre** — «o seu
    pedido foi enviado» — de propósito, para não confirmar que o projeto
    existe. Ou seja: a pessoa escrevia o que precisava, lia que tinha sido
    enviado, e não tinha sido. Nada gravado, ninguém avisado, e nenhuma
    maneira de dar por isso.

    Pergunta-se ao mesmo sítio que decide o acesso aos dados. Uma segunda
    definição de «pertence» acabaria por divergir — e a divergência aparece
    assim.
    """
    from src.services.acesso_ao_projeto import papel_no_projeto

    return await papel_no_projeto(db, user.id, space_id) is not None


@router.post(
    "",
    response_model=Recibo,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pedir dados para um projeto",
)
async def criar_pedido(
    corpo: PedidoNovo,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Recibo:
    """Grava o pedido e devolve sempre a mesma frase.

    202 e não 201: o que fica feito é o registo, não a decisão. E o mapeamento
    para tabelas corre depois — se corresse aqui, o tempo de resposta dizia se
    houve correspondência (S2).
    """
    if not await _pertence_ao_projeto(db, current_user, corpo.space_id):
        # Mesma frase de sempre. Um 403 aqui confirmaria que o projeto existe.
        return Recibo(mensagem=pedidos.RESPOSTA)

    try:
        msg = await pedidos.criar(
            db,
            requester_id=current_user.id,
            space_id=corpo.space_id,
            texto=corpo.texto,
        )
    except pedidos.LimiteDePedidos as limite:
        # Também aqui a frase é a de sempre: dizer "passaste do limite" conta a
        # quem sonda que os pedidos anteriores foram a algum lado (S3).
        logger.warning("pedido_de_acesso_acima_do_limite", extra={"user": str(current_user.id)})
        return Recibo(mensagem=str(limite))
    except pedidos.PedidoInvalido as erro:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))

    await db.commit()
    return Recibo(mensagem=msg)


# ── A partir daqui é só para quem aprova ─────────────────────────────────────


def _so_admin(user: User) -> None:
    if not is_tenant_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Não pode decidir pedidos de acesso.")


@router.get(
    "/meus",
    summary="Os pedidos que EU fiz",
    description=(
        "Depois de pedir, a app dizia «o seu pedido foi enviado» e acabava "
        "aí — sem lista, sem estado, sem forma de saber se alguém tinha "
        "olhado. É esta a lista que faltava."
    ),
)
async def meus_pedidos(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """Sem portão nenhum: são os pedidos da própria pessoa.

    Vai o **estado** e o motivo da decisão, que é o que se quer saber. Não vai
    a `proposta`: é a tradução do pedido em tabelas concretas, feita do lado
    de quem aprova, e mostrá-la a quem pediu era mostrar-lhe nomes de tabelas
    a que pode não ter acesso — exactamente o que o pedido existe para evitar.
    """
    linhas = (
        (
            await db.execute(
                select(DataAccessRequest, Space.name)
                .join(Space, Space.id == DataAccessRequest.space_id)
                .where(DataAccessRequest.requester_user_id == current_user.id)
                .order_by(DataAccessRequest.created_at.desc())
                .limit(100)
            )
        )
        .all()
    )
    return [
        {
            "id": str(pedido.id),
            "space_id": str(pedido.space_id),
            "projeto": nome_do_projeto,
            "texto": pedido.texto,
            "status": pedido.status,
            "motivo_decisao": pedido.motivo_decisao,
            "expires_at": pedido.expires_at.isoformat() if pedido.expires_at else None,
            "created_at": pedido.created_at.isoformat() if pedido.created_at else None,
            "decided_at": pedido.decided_at.isoformat() if pedido.decided_at else None,
        }
        for pedido, nome_do_projeto in linhas
    ]


@router.get(
    "/do-projeto/{space_id}",
    summary="Os pedidos de dados deste projeto",
    description=(
        "A lista de tarefas de quem trata dos dados: o que foi pedido para "
        "este projeto e ainda ninguém decidiu."
    ),
    responses={403: {"model": ErrorResponse}},
)
async def pedidos_do_projeto(
    space_id: UUID,
    estado: Optional[str] = Query(
        None, pattern="^(pending|proposed|approved|rejected|expired)$"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """**Quem manda aqui é o projeto, não a plataforma.**

    A lista global é de administradores do cliente. Esta é de quem trata dos
    dados **deste** projeto — que muitas vezes não é a mesma pessoa, e que
    era quem estava a ficar sem saber que havia pedidos à espera.
    """
    from src.services.acesso_ao_projeto import papel_no_projeto

    papel = await papel_no_projeto(db, current_user.id, space_id)
    if papel not in ("owner", "editor") and not is_tenant_admin(current_user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Não pode ver os pedidos deste projeto."
        )

    q = select(DataAccessRequest).where(DataAccessRequest.space_id == space_id)
    if estado:
        q = q.where(DataAccessRequest.status == estado)
    linhas = (
        (await db.execute(q.order_by(DataAccessRequest.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return [
        {
            "id": str(pedido.id),
            "space_id": str(pedido.space_id),
            "requester_user_id": str(pedido.requester_user_id),
            "texto": pedido.texto,
            "proposta": pedido.proposta,
            "status": pedido.status,
            "created_at": pedido.created_at.isoformat() if pedido.created_at else None,
        }
        for pedido in linhas
    ]


@router.get("", summary="Pedidos por decidir (admin do cliente)")
async def listar(
    estado: str = Query("pending", pattern="^(pending|proposed|approved|rejected|expired)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    _so_admin(current_user)
    linhas = (
        (
            await db.execute(
                select(DataAccessRequest)
                .where(DataAccessRequest.status == estado)
                .order_by(DataAccessRequest.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(p.id),
            "space_id": str(p.space_id),
            "requester_user_id": str(p.requester_user_id),
            # O texto original vai sempre ao lado da proposta: o aprovador julga
            # o que a pessoa pediu, não o que a máquina entendeu.
            "texto": p.texto,
            "proposta": p.proposta,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in linhas
    ]


async def _carregar(db: AsyncSession, pedido_id: UUID) -> DataAccessRequest:
    p = (
        await db.execute(select(DataAccessRequest).where(DataAccessRequest.id == pedido_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido não encontrado.")
    return p


@router.post("/{pedido_id}/proposta", summary="Traduzir o pedido em tabelas (admin)")
async def propor(
    pedido_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    _so_admin(current_user)
    p = await _carregar(db, pedido_id)
    proposta = await pedidos.propor(db, p)
    ja_tem = pedidos.ja_no_projeto_da_ultima_proposta(str(p.id))
    await db.commit()
    # `ja_no_projeto` separa duas coisas que o ecrã mostrava iguais: "não há
    # nada que corresponda" e "corresponde, mas este projeto já tem". A segunda
    # não é uma recusa — é um "já tens acesso a isso".
    return {
        "id": str(p.id),
        "status": p.status,
        "proposta": proposta,
        "ja_no_projeto": ja_tem,
    }


@router.post("/{pedido_id}/aprovar", summary="Aprovar, com prazo (admin)")
async def aprovar(
    pedido_id: UUID,
    corpo: Decisao,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    _so_admin(current_user)
    p = await _carregar(db, pedido_id)
    try:
        novas = await pedidos.aprovar(
            db,
            p,
            aprovador_id=current_user.id,
            tabelas=corpo.tabelas,
            prazo_dias=corpo.prazo_dias,
            motivo=corpo.motivo,
        )
    except pedidos.PedidoInvalido as erro:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    await db.commit()
    return {
        "id": str(p.id),
        "status": p.status,
        "tabelas": novas,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
    }


@router.post("/{pedido_id}/recusar", summary="Recusar (admin)")
async def recusar(
    pedido_id: UUID,
    corpo: Decisao,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    _so_admin(current_user)
    p = await _carregar(db, pedido_id)
    try:
        await pedidos.recusar(db, p, aprovador_id=current_user.id, motivo=corpo.motivo)
    except pedidos.PedidoInvalido as erro:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    await db.commit()
    return {"id": str(p.id), "status": p.status}
