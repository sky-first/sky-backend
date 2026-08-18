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
    if (
        await db.execute(
            select(SpaceMember.id).where(
                SpaceMember.space_id == space_id, SpaceMember.user_id == user.id
            )
        )
    ).first():
        return True
    return (
        await db.execute(select(Space.id).where(Space.id == space_id, Space.created_by == user.id))
    ).first() is not None


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
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Não podes decidir pedidos de acesso.")


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
    await db.commit()
    return {"id": str(p.id), "status": p.status, "proposta": proposta}


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
