"""Duas regras da conta para a web e a app lerem igual (paridade 13/10/2026).

1. **Língua das respostas por omissão = «Segue a sua pergunta» (`auto`).**
   Com `answer_language` vazio a web respondia na língua da interface e a app
   seguia a pergunta: a mesma conta, línguas diferentes conforme o aparelho.
2. **`preferences.theme` só guarda claro/escuro.** «Sistema» fica em cada
   aparelho; um `"system"` que chegue é ignorado (fica o que lá estava).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.core.locale import lingua_da_resposta
from src.core.preferences import (
    preferencias_para_ler,
    sanear_ao_gravar,
    sem_tema_do_aparelho,
)


def _h(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ─── Língua das respostas ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "prefs", [None, {}, {"language": "es"}, {"answer_language": ""}, {"answer_language": "  "}]
)
def test_sem_escolha_segue_a_pergunta(prefs):
    assert lingua_da_resposta(prefs, permitir_auto=True) == "auto"


def test_quem_nao_sabe_de_auto_continua_na_interface():
    """Textos sem pergunta (agente na fila, SQL gerado) não têm de onde tirar
    a língua: ficam na da interface, como antes."""
    assert lingua_da_resposta({"language": "es"}) == "es"


def test_escolha_explicita_continua_a_valer():
    assert (
        lingua_da_resposta({"language": "es", "answer_language": "pt"}, permitir_auto=True) == "pt"
    )


def test_leitura_marca_auto_quando_a_conta_nunca_escolheu():
    assert preferencias_para_ler({"language": "es"})["answer_language"] == "auto"
    assert preferencias_para_ler({"answer_language": ""})["answer_language"] == "auto"
    assert preferencias_para_ler({"answer_language": "en"})["answer_language"] == "en"
    # Não mexe no original (o dicionário do SQLAlchemy).
    original = {"language": "es"}
    preferencias_para_ler(original)
    assert original == {"language": "es"}


@pytest.mark.asyncio
async def test_auth_me_e_settings_mostram_auto(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    h = _h(test_user_with_tokens)
    r = await async_client.put(
        "/api/v1/settings", headers=h, json={"preferences": {"language": "es"}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["preferences"]["answer_language"] == "auto"
    r = await async_client.get("/api/v1/settings", headers=h)
    assert r.json()["preferences"]["answer_language"] == "auto"
    r = await async_client.get("/api/v1/auth/me", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["preferences"]["answer_language"] == "auto"
    r = await async_client.get("/api/v1/users/me", headers=h)
    assert r.json()["preferences"]["answer_language"] == "auto"


@pytest.mark.asyncio
async def test_stream_sem_escolha_deixa_o_motor_detectar(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Sem `locale` no pedido e sem `answer_language` na conta, o motor recebe
    `locale=None` (detecta a língua da pergunta) — e não a da interface."""
    h = _h(test_user_with_tokens)
    await async_client.put("/api/v1/settings", headers=h, json={"preferences": {"language": "es"}})

    captured: dict = {}

    async def _engine(*a, **k):
        captured.update(k)
        yield 'data: {"type": "chunk", "content": "ok"}'

    with (
        patch(
            "src.services.ai_service.AIService._get_first_active_connection",
            new=AsyncMock(return_value=str(uuid4())),
        ),
        patch(
            "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
            side_effect=_engine,
        ),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={"message": "how many clients?", "widget_id": str(uuid4())},
            headers=h,
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_text():
                pass
    assert "locale" in captured
    assert captured["locale"] is None
    # A interface continua na língua da app.
    assert captured.get("ui_locale") == "es"


# ─── Tema ───────────────────────────────────────────────────────────────


def test_system_e_ignorado_ao_escrever():
    assert sem_tema_do_aparelho({"theme": "system", "language": "pt"}) == {"language": "pt"}
    assert sem_tema_do_aparelho({"theme": "Dark"}) == {"theme": "dark"}
    # null continua a apagar.
    assert sem_tema_do_aparelho({"theme": None}) == {"theme": None}


def test_system_legado_sai_ao_ler_e_ao_gravar():
    assert "theme" not in preferencias_para_ler({"theme": "system"})
    assert preferencias_para_ler({"theme": "light"})["theme"] == "light"
    assert sanear_ao_gravar({"theme": "system", "language": "es"}) == {"language": "es"}


@pytest.mark.asyncio
async def test_app_manda_system_e_a_conta_fica_com_o_escuro(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    h = _h(test_user_with_tokens)
    r = await async_client.put(
        "/api/v1/settings", headers=h, json={"preferences": {"theme": "dark"}}
    )
    assert r.json()["preferences"]["theme"] == "dark"

    # A app (PUT /settings), pelas duas formas que conhece.
    r = await async_client.put(
        "/api/v1/settings", headers=h, json={"preferences": {"theme": "system"}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["preferences"]["theme"] == "dark"
    r = await async_client.put("/api/v1/settings", headers=h, json={"theme": "system"})
    assert r.json()["theme"] == "dark"

    # A web (PUT /users/me).
    r = await async_client.put(
        "/api/v1/users/me", headers=h, json={"preferences": {"theme": "system"}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["preferences"]["theme"] == "dark"

    r = await async_client.get("/api/v1/auth/me", headers=h)
    assert r.json()["preferences"]["theme"] == "dark"


@pytest.mark.asyncio
async def test_system_gravado_antes_desta_regra_nao_volta_a_sair(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session
):
    from sqlalchemy.orm.attributes import flag_modified

    user = test_user_with_tokens["user"]
    user.preferences = {"theme": "system", "language": "pt"}
    flag_modified(user, "preferences")
    await db_session.commit()

    h = _h(test_user_with_tokens)
    r = await async_client.get("/api/v1/auth/me", headers=h)
    assert "theme" not in r.json()["preferences"]
    r = await async_client.get("/api/v1/settings", headers=h)
    assert "theme" not in r.json()["preferences"]

    # A próxima escrita limpa-o da base.
    await async_client.put("/api/v1/settings", headers=h, json={"preferences": {"language": "es"}})
    await db_session.refresh(user)
    assert "theme" not in (user.preferences or {})
