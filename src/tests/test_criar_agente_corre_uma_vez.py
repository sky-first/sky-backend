"""Criar um agente corre-o UMA vez, não duas.

O ``POST /agents/`` já põe a estreia na fila; a app chamava ``/run`` logo a
seguir e o agente corria duas vezes, gastando duas perguntas do plano
(auditoria da app, 12/10/2026). Mede-se o que vai para a fila do worker.
"""

from __future__ import annotations

import pytest

from src.services import estreia_do_agente


class _Fila:
    def __init__(self):
        self.pedidos: list = []

    def delay(self, *a, **k):
        self.pedidos.append((a, k))


class _RedisFalso:
    def __init__(self):
        self.d: dict = {}

    async def set(self, k, v, ex=None):
        self.d[k] = v

    async def delete(self, k):
        return 1 if self.d.pop(k, None) is not None else 0


@pytest.fixture
def fila(monkeypatch):
    from src.workers import agent_worker

    f = _Fila()
    monkeypatch.setattr(agent_worker.execute_agent, "delay", f.delay)
    return f


@pytest.fixture
def redis_falso(monkeypatch):
    r = _RedisFalso()

    async def _r():
        return r

    monkeypatch.setattr(estreia_do_agente, "_redis", _r)
    return r


@pytest.mark.asyncio
async def test_criar_e_logo_run_poe_uma_so_corrida_na_fila(
    async_client, test_user_with_tokens, fila, redis_falso
):
    h = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    user = test_user_with_tokens["user"]
    r = await async_client.post(
        "/api/v1/agents/",
        json={
            "name": "Margens",
            "scope": "personal",
            "scope_id": str(user.id),
            "monitor_type": "question",
            "focus": "Como estão as margens?",
            "frequency": "daily",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]
    assert len(fila.pedidos) == 1  # a estreia

    r = await async_client.post(f"/api/v1/agents/{agent_id}/run", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["already_queued"] is True
    assert len(fila.pedidos) == 1  # NÃO repetiu

    # Um segundo toque é um pedido explícito: corre.
    r = await async_client.post(f"/api/v1/agents/{agent_id}/run", headers=h)
    assert r.json()["already_queued"] is False
    assert len(fila.pedidos) == 2


@pytest.mark.asyncio
async def test_sem_redis_continua_a_correr(monkeypatch):
    async def _sem():
        return None

    monkeypatch.setattr(estreia_do_agente, "_redis", _sem)
    await estreia_do_agente.marcar("x")
    assert await estreia_do_agente.ja_esta_na_fila("x") is False
