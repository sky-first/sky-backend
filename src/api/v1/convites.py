"""Convites a projetos — do lado de quem os recebe.

**Porque estas rotas não vivem em `spaces.py`.** Porque `/spaces/{space_id}`
está declarada lá e apanha tudo o que seja um segmento a seguir a `/spaces`:
`/spaces/meus-convites` seria lido como *o projeto chamado "meus-convites"* e
morria em `422` antes de chegar à função. Dava para resolver com a ordem de
declaração — e ficava a partir-se na primeira vez que alguém arrumasse o
ficheiro. Um prefixo próprio não tem essa aresta.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.services.space_service import SpaceService

router = APIRouter()


@router.get(
    "",
    summary="Os convites à minha espera",
    description="Convites a projetos que ainda não respondi.",
)
async def meus_convites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    return await SpaceService(db).meus_convites(current_user)


@router.post(
    "/{convite_id}/responder",
    summary="Aceitar ou recusar um convite",
    description=(
        "**Só a pessoa convidada** responde — nem quem convidou responde por "
        "ela. Ao aceitar, entra no projeto pela equipa Geral e o projeto "
        "inteiro é notificado."
    ),
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def responder_ao_convite(
    convite_id: UUID,
    aceitar: bool = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    return await SpaceService(db).responder_ao_convite(convite_id, current_user, aceitar)
