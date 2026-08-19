"""Convidar alguém que não existe é 404, não 500.

Apanhado a sondar em produção o que um member alcança depois de criar um
projeto seu:

    POST /api/v1/spaces/{o_meu}/members  {"user_id": "0000...", ...}  ->  500

Não havia verificação nenhuma de que a pessoa existe. O `create` metia a linha
e a chave estrangeira `space_members.user_id -> users.id` é que recusava — o
que sai como 500.

Para quem está a convidar um colega isto é pior do que parece: vê "erro do
servidor" e não sabe se o problema é o convite, a permissão dele, ou a
plataforma estar em baixo. Com 404 sabe que escreveu a pessoa errada.
"""

from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import NotFoundError
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.schemas.space import SpaceMemberCreate
from src.services.space_service import SpaceService


async def _dono_com_projeto(db) -> tuple[User, Space]:
    dono = User(
        id=uuid.uuid4(),
        email=f"d-{uuid.uuid4().hex[:6]}@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name="Dono",
    )
    db.add(dono)
    await db.flush()
    projeto = Space(name=f"P {uuid.uuid4().hex[:6]}", created_by=dono.id)
    db.add(projeto)
    await db.flush()
    db.add(SpaceMember(space_id=projeto.id, user_id=dono.id, role="owner"))
    await db.commit()
    return dono, projeto


@pytest.mark.asyncio
async def test_pessoa_inexistente_da_404(db_session):
    dono, projeto = await _dono_com_projeto(db_session)
    svc = SpaceService(db_session)

    with pytest.raises(NotFoundError, match="User not found"):
        await svc.add_space_member(
            projeto.id,
            dono,
            SpaceMemberCreate(user_id=uuid.uuid4(), role="viewer"),
        )


@pytest.mark.asyncio
async def test_pessoa_que_existe_continua_a_entrar(db_session):
    """A outra metade — a verificação não pode partir o caso normal."""
    dono, projeto = await _dono_com_projeto(db_session)
    convidado = User(
        id=uuid.uuid4(),
        email=f"c-{uuid.uuid4().hex[:6]}@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name="Convidado",
    )
    db_session.add(convidado)
    await db_session.commit()

    membro = await SpaceService(db_session).add_space_member(
        projeto.id,
        dono,
        SpaceMemberCreate(user_id=convidado.id, role="viewer"),
    )
    assert str(membro.user_id) == str(convidado.id)
    assert membro.role == "viewer"
