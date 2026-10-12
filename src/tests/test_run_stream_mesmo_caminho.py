"""`POST /agents/{id}/run/stream` passa pelo MESMO caminho do `/run`.

A rota antiga corria o agente dentro da API, ao lado do worker, e saltava
tudo o que o worker passou a fazer: a pergunta do plano, o acesso do dono às
fontes (#745), o recorte por equipa, o modo «contexto» (#746), a mensagem no
fio do agente e o `last_answer`. E dava 400 «Agent has no connections to
analyze» a todos os agentes criados na app (`connection_ids=[]`).

Estes testes medem o que a rota FAZ — o que vai (ou não) para a fila do
worker e o código HTTP — e não o texto da função.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException

from src.api.v1 import agents as rota
from src.models.agent import Agent
from src.services import limites_do_plano as lim


class _Fila:
    def __init__(self):
        self.pedidos: list = []

    def delay(self, *a, **k):
        self.pedidos.append((a, k))


@pytest.fixture
def fila(monkeypatch):
    from src.workers import agent_worker

    f = _Fila()
    monkeypatch.setattr(agent_worker.execute_agent, "delay", f.delay)

    # O caminho antigo chamava o sky-ai DENTRO da API. Se alguém o
    # ressuscitar, rebenta aqui em vez de passar em silêncio.
    from src.ai import http_client

    class _Proibido:
        def __init__(self, *a, **k):
            raise AssertionError("/run/stream não pode chamar o sky-ai directamente")

    monkeypatch.setattr(http_client, "AIServiceHTTPClient", _Proibido)
    return f


async def _pessoa(db, lingua="pt"):
    from src.core.security import get_password_hash
    from src.repositories.user import UserRepository

    u = await UserRepository(db).create(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Dono",
        role="member",
    )
    u.preferences = {"language": lingua}
    await db.commit()
    return u


async def _agente(db, dono, *, ligacoes=()):
    a = Agent(
        name="Quanto faturei?",
        scope="personal",
        scope_id=str(dono.id),
        status="active",
        monitor_type="question",
        focus="Quanto faturei?",
        frequency="manual",
        connection_ids=[str(x) for x in ligacoes],
        created_by=dono.id,
    )
    db.add(a)
    await db.commit()
    return a


async def _ler(resp) -> list:
    eventos = []
    async for bloco in resp.body_iterator:
        texto = bloco.decode() if isinstance(bloco, bytes) else bloco
        for linha in texto.split("\n"):
            if linha.startswith("data: "):
                eventos.append(json.loads(linha[6:]))
    return eventos


@pytest.mark.asyncio
async def test_agente_sem_ligacoes_ja_nao_da_400_e_vai_para_o_worker(db_session, fila):
    """O agente criado na app (`connection_ids=[]`) corre — pelo worker."""
    dono = await _pessoa(db_session)
    agente = await _agente(db_session, dono, ligacoes=())

    resp = await rota.run_agent_stream(agent_id=agente.id, current_user=dono, db=db_session)
    eventos = await _ler(resp)

    assert len(fila.pedidos) == 1
    args, kwargs = fila.pedidos[0]
    assert args == (str(agente.id),)
    assert kwargs == {"a_pedido": True}
    assert [e["type"] for e in eventos] == ["progress", "chunk", "done"]
    assert eventos[-1]["queued"] is True
    assert eventos[-1]["agent_id"] == str(agente.id)
    # A frase vem na língua de quem carregou, não em inglês cravado.
    assert "conversa do agente" in eventos[1]["content"]


@pytest.mark.asyncio
async def test_sem_perguntas_no_mes_da_402_e_nao_corre(db_session, fila, monkeypatch):
    dono = await _pessoa(db_session)
    agente = await _agente(db_session, dono)

    async def _sem_saldo():
        raise lim.LimiteDoPlanoError(
            recurso="max_queries_per_month", limite=500, atual=500, plano="starter"
        )

    monkeypatch.setattr(lim, "verificar_saldo", _sem_saldo)

    with pytest.raises(lim.LimiteDoPlanoError):
        await rota.run_agent_stream(agent_id=agente.id, current_user=dono, db=db_session)
    assert fila.pedidos == []


@pytest.mark.asyncio
async def test_quem_nao_e_dono_nao_corre_o_agente_pessoal_de_outro(db_session, fila):
    dono = await _pessoa(db_session)
    outro = await _pessoa(db_session)
    agente = await _agente(db_session, dono)

    with pytest.raises(HTTPException) as e:
        await rota.run_agent_stream(agent_id=agente.id, current_user=outro, db=db_session)
    assert e.value.status_code == 403
    assert fila.pedidos == []


@pytest.mark.asyncio
async def test_agente_inexistente_da_404(db_session, fila):
    dono = await _pessoa(db_session)
    with pytest.raises(HTTPException) as e:
        await rota.run_agent_stream(agent_id=uuid.uuid4(), current_user=dono, db=db_session)
    assert e.value.status_code == 404
    assert fila.pedidos == []


@pytest.mark.asyncio
async def test_as_duas_rotas_pedem_o_mesmo_ao_worker(db_session, fila):
    """`/run` e `/run/stream`: a mesma tarefa, com os mesmos argumentos.

    É no worker que vivem o acesso do dono às fontes, o recorte por equipa,
    o modo «contexto», a reserva da pergunta e a mensagem no fio. Pedir o
    mesmo ao worker é herdar tudo isso.
    """
    dono = await _pessoa(db_session)
    agente = await _agente(db_session, dono)

    corrida = await rota.run_agent_now(agent_id=agente.id, current_user=dono, db=db_session)
    resp = await rota.run_agent_stream(agent_id=agente.id, current_user=dono, db=db_session)
    eventos = await _ler(resp)

    assert fila.pedidos[0] == fila.pedidos[1]
    assert eventos[-1]["conversation_id"] == corrida["conversation_id"]
