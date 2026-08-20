"""Conversas sem uma única mensagem não aparecem na lista.

O Lucas: *«nao podemos ter conversas sem titulo ou sem texto, se eu abrir uma
conversa e nao digitar nada, esta deve ser removida, pois agora temos varios sem
titulo»*.

A causa está no desenho dos dois clientes: ambos **criam a conversa e só depois
mandam a mensagem**. Se algo falhar no meio — rede, a pessoa fecha a app, muda de
ideias — fica uma conversa sem mensagens. E sem título, porque o título só é
posto quando a primeira mensagem chega (``message_service.py``).

O filtro vive no repositório e não no cliente, por duas razões:

1. são **dois** clientes com o mesmo defeito, e um filtro no servidor corrige os
   dois de uma vez;
2. é um filtro de **leitura** — as linhas ficam na base. Esconder é reversível;
   apagar não é, e apagar automaticamente o que um cliente acabou de criar seria
   uma corrida perdida à partida.

A carência existe precisamente por causa dessa corrida: entre criar a conversa e
gravar a primeira mensagem há dois pedidos, e durante esse intervalo a conversa
tem legitimamente zero mensagens.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.models.conversation import Conversation, Message
from src.repositories.conversation import (
    CARENCIA_SEM_MENSAGENS,
    ConversationRepository,
)


def _conversa(page_id, user_id, *, criada_em):
    return Conversation(
        id=uuid4(),
        page_id=page_id,
        created_by=user_id,
        created_at=criada_em,
        updated_at=criada_em,
    )


async def _listar(db, page_id, user_id):
    return await ConversationRepository(db).list_for_page(
        page_id=page_id, user_id=user_id, user_space_ids=[], user_crew_ids=[]
    )


@pytest.mark.asyncio
async def test_conversa_vazia_e_antiga_nao_aparece(db_session):
    page_id, user_id = uuid4(), uuid4()
    velha = _conversa(
        page_id, user_id, criada_em=datetime.now(timezone.utc) - timedelta(days=1)
    )
    db_session.add(velha)
    await db_session.commit()

    assert await _listar(db_session, page_id, user_id) == []


@pytest.mark.asyncio
async def test_conversa_vazia_mas_acabada_de_criar_aparece(db_session):
    """A corrida entre os dois pedidos do cliente.

    Sem esta carência, a conversa desaparecia da lista no instante entre ser
    criada e receber a primeira mensagem — e o cliente que a acabou de criar
    ficava a olhar para uma lista onde ela não está.
    """
    page_id, user_id = uuid4(), uuid4()
    nova = _conversa(page_id, user_id, criada_em=datetime.now(timezone.utc))
    db_session.add(nova)
    await db_session.commit()

    assert [c.id for c in await _listar(db_session, page_id, user_id)] == [nova.id]


@pytest.mark.asyncio
async def test_conversa_antiga_com_mensagem_aparece(db_session):
    page_id, user_id = uuid4(), uuid4()
    antiga = _conversa(
        page_id, user_id, criada_em=datetime.now(timezone.utc) - timedelta(days=30)
    )
    db_session.add(antiga)
    await db_session.flush()
    db_session.add(
        Message(
            id=uuid4(),
            conversation_id=antiga.id,
            role="user",
            kind="question",
            content="qual foi o custo por canal em Julho?",
        )
    )
    await db_session.commit()

    assert [c.id for c in await _listar(db_session, page_id, user_id)] == [antiga.id]


@pytest.mark.asyncio
async def test_esconder_nao_e_apagar(db_session):
    """A linha continua na base — isto é um filtro de leitura.

    Importa porque um cliente com a conversa aberta continua a poder gravar-lhe
    a primeira mensagem, e nesse momento ela volta à lista. Se tivéssemos
    apagado, a mensagem batia numa chave estrangeira que já não existe.
    """
    page_id, user_id = uuid4(), uuid4()
    velha = _conversa(
        page_id, user_id, criada_em=datetime.now(timezone.utc) - timedelta(days=1)
    )
    db_session.add(velha)
    await db_session.commit()

    assert await _listar(db_session, page_id, user_id) == []
    assert await db_session.get(Conversation, velha.id) is not None

    db_session.add(
        Message(
            id=uuid4(),
            conversation_id=velha.id,
            role="user",
            kind="question",
            content="afinal sempre tenho uma pergunta",
        )
    )
    await db_session.commit()

    assert [c.id for c in await _listar(db_session, page_id, user_id)] == [velha.id]


def test_a_carencia_e_curta_mas_nao_apertada():
    """Fixa a intenção, não o número.

    Curta de mais e a conversa recém-criada pisca fora da lista num cliente
    lento. Longa de mais e o lixo do dia fica visível o dia todo.
    """
    assert timedelta(minutes=1) <= CARENCIA_SEM_MENSAGENS <= timedelta(minutes=30)
