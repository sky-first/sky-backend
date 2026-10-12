"""Preferências: fusão em profundidade (auditoria web, 12/10/2026, §0.6 / W9).

O telemóvel grava ``voice.patience``; a web grava ``voice.voice``. Com a
fusão só ao primeiro nível, o segundo ``PUT`` apagava o que o primeiro tinha
gravado. As duas rotas que escrevem ``users.preferences`` (``PUT /settings``
da app e ``PUT /users/me`` da web) fundem agora em profundidade, e uma chave a
``null`` apaga-a.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.core.preferences import deep_merge_preferences


def test_fusao_profunda_mantem_irmaos_e_null_apaga():
    base = {"voice": {"voice": "lupe", "patience": "patient"}, "theme": "dark"}
    patch = {"voice": {"voice": "sergio", "language": None}, "language": "pt"}
    out = deep_merge_preferences(base, patch)
    assert out == {
        "voice": {"voice": "sergio", "patience": "patient"},
        "theme": "dark",
        "language": "pt",
    }
    # Não mexe nos argumentos.
    assert base["voice"]["voice"] == "lupe"
    assert "language" not in base


def test_null_apaga_ao_primeiro_nivel_e_valor_escalar_substitui_dicionario():
    out = deep_merge_preferences({"voice": {"voice": "lupe"}, "theme": "dark"}, {"theme": None})
    assert out == {"voice": {"voice": "lupe"}}
    out = deep_merge_preferences({"voice": {"voice": "lupe"}}, {"voice": "off"})
    assert out == {"voice": "off"}
    out = deep_merge_preferences({}, {"voice": {"voice": "lupe", "patience": None}})
    assert out == {"voice": {"voice": "lupe"}}


def _h(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.mark.asyncio
async def test_telemovel_e_web_gravam_voz_sem_se_apagarem(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    h = _h(test_user_with_tokens)
    # O telemóvel grava a paciência (e o resto que tem).
    r = await async_client.put(
        "/api/v1/settings",
        headers=h,
        json={
            "preferences": {
                "language": "es",
                "answer_language": "auto",
                "theme": "dark",
                "voice": {"patience": "patient"},
            }
        },
    )
    assert r.status_code == 200, r.text

    # A web grava só a voz, pela sua rota.
    r = await async_client.put(
        "/api/v1/users/me", headers=h, json={"preferences": {"voice": {"voice": "lupe"}}}
    )
    assert r.status_code == 200, r.text

    # E o telemóvel volta a gravar só a voz, por /settings.
    r = await async_client.put(
        "/api/v1/settings", headers=h, json={"preferences": {"voice": {"language": "es"}}}
    )
    assert r.status_code == 200, r.text

    r = await async_client.get("/api/v1/settings", headers=h)
    prefs = r.json()["preferences"]
    assert prefs["voice"] == {"patience": "patient", "voice": "lupe", "language": "es"}
    assert prefs["language"] == "es"
    assert prefs["answer_language"] == "auto"
    assert prefs["theme"] == "dark"


@pytest.mark.asyncio
async def test_lingua_resposta_e_tema_mudam_cada_um_sem_tocar_nos_outros(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    h = _h(test_user_with_tokens)
    await async_client.put(
        "/api/v1/settings",
        headers=h,
        json={"preferences": {"language": "pt", "answer_language": "auto", "theme": "light"}},
    )
    for chave, valor in (("language", "en"), ("answer_language", "es"), ("theme", "dark")):
        r = await async_client.put(
            "/api/v1/settings", headers=h, json={"preferences": {chave: valor}}
        )
        assert r.status_code == 200, r.text

    r = await async_client.get("/api/v1/settings", headers=h)
    prefs = r.json()["preferences"]
    assert prefs["language"] == "en"
    assert prefs["answer_language"] == "es"
    assert prefs["theme"] == "dark"

    # Uma chave a null apaga só essa.
    r = await async_client.put(
        "/api/v1/settings", headers=h, json={"preferences": {"answer_language": None}}
    )
    assert r.status_code == 200
    prefs = (await async_client.get("/api/v1/settings", headers=h)).json()["preferences"]
    assert "answer_language" not in prefs
    assert prefs["language"] == "en" and prefs["theme"] == "dark"
