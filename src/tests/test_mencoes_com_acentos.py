"""«@Ángela» avisa a Ángela.

A app decidia «isto é uma menção» com ``@([a-zA-Z0-9_.-]+)``: com acento não
casava, a mensagem ia sem ``mentions`` e ninguém era avisado (auditoria da
app, 12/10/2026). O servidor passa a resolver o ``@nome`` do texto — sem
acentos e sem maiúsculas — mas só contra quem está na conversa, e só quando o
nome aponta para UMA pessoa. Os ids do cliente continuam a ganhar.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.services.mencoes import nomes_mencionados, normalizar


def test_normalizar_tira_acentos_e_maiusculas():
    assert normalizar("Ángela") == "angela"
    assert normalizar("ÓSCAR") == "oscar"
    assert normalizar("João.") == "joao"


def test_nomes_mencionados_apanha_acentos_e_ignora_emails_e_a_sky():
    texto = "@Ángela e @óscar vejam isto; manda para ana@empresa.com @Sky @all"
    assert nomes_mencionados(texto) == ["angela", "oscar"]


async def _pessoa(db, nome, email=None):
    from src.core.security import get_password_hash
    from src.repositories.user import UserRepository

    u = await UserRepository(db).create(
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name=nome,
        role="member",
    )
    await db.commit()
    return u


async def _sala(db, dono, membros):
    """Uma equipa com página e conversa; `membros` entram na equipa."""
    from src.models.conversation import Conversation
    from src.models.crew import Crew, CrewMember
    from src.models.page import Page
    from src.models.space import Space

    space = Space(name="Vendas", created_by=dono.id)
    db.add(space)
    await db.flush()
    crew = Crew(name="Geral", space_id=space.id, created_by=dono.id)
    db.add(crew)
    await db.flush()
    for p in [dono, *membros]:
        db.add(CrewMember(crew_id=crew.id, user_id=p.id, role="member"))
    page = Page(
        name="Sala", type="team", color="#FAB721", owner_id=dono.id,
        space_id=space.id, crew_id=crew.id,
    )
    db.add(page)
    await db.flush()
    conv = Conversation(page_id=page.id, created_by=dono.id, crew_id=crew.id, space_id=space.id)
    db.add(conv)
    await db.commit()
    return conv


async def _avisos(db, user_id):
    from src.models.notification import Notification

    db.expire_all()
    return (
        (await db.execute(select(Notification).where(Notification.user_id == user_id)))
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_comentario_com_acento_avisa_a_pessoa_da_equipa(db_session):
    from src.schemas.message import MessageCreate
    from src.services.message_service import MessageService

    dono = await _pessoa(db_session, "Lucas Ventura")
    angela = await _pessoa(db_session, "Ángela Ruiz")
    conv = await _sala(db_session, dono, [angela])
    conv_id, angela_id = conv.id, angela.id

    await MessageService(db_session).create(
        conv_id, dono, MessageCreate(content="@angela olha isto", kind="comment")
    )
    avisos = await _avisos(db_session, angela_id)
    assert [a.type for a in avisos] == ["comment_mention"]

    # E com o acento escrito, em maiúsculas.
    await db_session.refresh(dono)
    await MessageService(db_session).create(
        conv_id, dono, MessageCreate(content="@ÁNGELA e agora?", kind="comment")
    )
    assert len([a for a in await _avisos(db_session, angela_id) if a.type == "comment_mention"]) == 2


@pytest.mark.asyncio
async def test_nome_ambiguo_ou_de_fora_nao_avisa_ninguem(db_session):
    from src.schemas.message import MessageCreate
    from src.services.message_service import MessageService

    dono = await _pessoa(db_session, "Lucas Ventura")
    paulo_a = await _pessoa(db_session, "Paulo Richau")
    paulo_b = await _pessoa(db_session, "Paulo Bomfim")
    oscar_de_fora = await _pessoa(db_session, "Óscar Fora")
    conv = await _sala(db_session, dono, [paulo_a, paulo_b])
    ids = [paulo_a.id, paulo_b.id, oscar_de_fora.id]

    await MessageService(db_session).create(
        conv.id, dono, MessageCreate(content="@paulo e @oscar", kind="comment")
    )
    for uid in ids:
        assert [a for a in await _avisos(db_session, uid) if a.type == "comment_mention"] == []


@pytest.mark.asyncio
async def test_ids_do_cliente_ganham_e_nao_duplicam(db_session):
    from src.schemas.message import MessageCreate
    from src.services.message_service import MessageService

    dono = await _pessoa(db_session, "Lucas Ventura")
    angela = await _pessoa(db_session, "Ángela Ruiz")
    conv = await _sala(db_session, dono, [angela])
    angela_id = angela.id

    await MessageService(db_session).create(
        conv.id,
        dono,
        MessageCreate(content="@Ángela olha", kind="comment", mentions=[angela_id]),
    )
    avisos = await _avisos(db_session, angela_id)
    # Uma menção, e nenhum aviso de «a conversa mexeu-se» por cima.
    assert [a.type for a in avisos] == ["comment_mention"]
