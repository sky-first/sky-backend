"""Arquivar um projeto tira-o das listas — e grava mesmo.

O modelo `Space` não mapeava a coluna `archived_at` (criada pela migração
`equipa_no_projeto_20260826`): `arquivar` escrevia num atributo Python que não
ia para a base, e a lista nem filtrava (auditoria da app, 12/10/2026).
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_arquivar_e_reabrir(async_client, test_user_with_tokens):
    h = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    r = await async_client.post("/api/v1/spaces", json={"name": "Teste"}, headers=h)
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]

    ids = lambda resp: [s["id"] for s in resp.json()]  # noqa: E731
    assert sid in ids(await async_client.get("/api/v1/spaces", headers=h))

    r = await async_client.post(f"/api/v1/spaces/{sid}/arquivar", headers=h)
    assert r.status_code == 200, r.text

    activos = await async_client.get("/api/v1/spaces", headers=h)
    assert sid not in ids(activos)
    arquivados = await async_client.get("/api/v1/spaces?archived=true", headers=h)
    assert ids(arquivados) == [sid]
    assert arquivados.json()[0]["archived_at"] is not None

    # Continua a abrir-se (os dados ficam), e reabre-se.
    assert (await async_client.get(f"/api/v1/spaces/{sid}", headers=h)).status_code == 200
    r = await async_client.post(f"/api/v1/spaces/{sid}/arquivar?reabrir=true", headers=h)
    assert r.status_code == 200, r.text
    assert sid in ids(await async_client.get("/api/v1/spaces", headers=h))
    assert ids(await async_client.get("/api/v1/spaces?archived=true", headers=h)) == []
