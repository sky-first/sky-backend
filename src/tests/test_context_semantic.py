"""Tests for the Universe Intelligence v2 BE proxy.

The proxy resolves the caller's ACL scope (Personal = own user_id +
every Space they belong to; ``space:<uuid>`` = membership-checked) and
forwards to the AI service. These tests verify:

  * Auth required (401 when missing token).
  * ACL resolution paths: personal, space membership, space without
    membership (404), malformed scope (400).
  * AI service unreachable → 503; AI returns non-200 → 502.
  * Successful proxy round-trips both endpoints (with httpx mocked).
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient, ConnectError, Response
from sqlalchemy.ext.asyncio import AsyncSession


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── Helper — build an httpx mock response ────────────────────────────


def _ok_map_response() -> Dict[str, Any]:
    return {
        "points": [
            {
                "id": str(uuid4()),
                "kind": "column",
                "label": "orders.amount",
                "snippet": "Table: orders | Column: amount",
                "x": 0.1,
                "y": 0.2,
                "z": 0.3,
                "cluster_id": 0,
                "source": "table_metadata",
            }
        ],
        "model": "nomic-embed-text",
        "dim": 768,
        "count": 1,
        "n_clusters": 1,
        "umap_params": {
            "n_neighbors": 15,
            "min_dist": 0.1,
            "n_components": 3,
            "metric": "cosine",
        },
    }


def _ok_search_response() -> Dict[str, Any]:
    return {
        "query": "revenue",
        "hits": [
            {
                "id": str(uuid4()),
                "score": 0.42,
                "kind": "column",
                "label": "orders.amount",
                "snippet": None,
            }
        ],
        "model": "nomic-embed-text",
        "dim": 768,
    }


def _fake_response(status_code: int, json_body: Dict[str, Any]) -> Response:
    return Response(status_code=status_code, json=json_body)


# ─── /context/semantic-map ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_semantic_map_unauthenticated_returns_401(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/context/semantic-map")
    assert resp.status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    }


@pytest.mark.asyncio
async def test_semantic_map_personal_scope_proxies_to_ai(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    body = _ok_map_response()
    with patch(
        "src.api.v1.context_semantic.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_fake_response(200, body))
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = await async_client.get(
            "/api/v1/context/semantic-map?scope=personal",
            headers=_auth(test_user_with_tokens["access_token"]),
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["count"] == 1
    assert data["points"][0]["kind"] == "column"


@pytest.mark.asyncio
async def test_semantic_map_personal_passes_user_id_to_ai(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    body = _ok_map_response()
    captured: Dict[str, Any] = {}
    with patch(
        "src.api.v1.context_semantic.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()

        async def _capture(url, json):
            captured["url"] = url
            captured["json"] = json
            return _fake_response(200, body)

        mock_client.post = _capture
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = await async_client.get(
            "/api/v1/context/semantic-map?scope=personal",
            headers=_auth(test_user_with_tokens["access_token"]),
        )
    assert resp.status_code == 200
    assert captured["url"].endswith("/semantic/map")
    assert captured["json"]["user_id"] == str(test_user_with_tokens["user"].id)
    assert captured["json"]["include_personal"] is True


@pytest.mark.asyncio
async def test_semantic_map_invalid_scope_returns_400(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    resp = await async_client.get(
        "/api/v1/context/semantic-map?scope=nonsense",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_semantic_map_space_scope_invalid_uuid_returns_400(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    resp = await async_client.get(
        "/api/v1/context/semantic-map?scope=space:not-a-uuid",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_semantic_map_space_scope_without_membership_returns_404(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    foreign_space = uuid4()
    resp = await async_client.get(
        f"/api/v1/context/semantic-map?scope=space:{foreign_space}",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_semantic_map_ai_service_503_when_unreachable(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    with patch(
        "src.api.v1.context_semantic.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectError("nope"))
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = await async_client.get(
            "/api/v1/context/semantic-map?scope=personal",
            headers=_auth(test_user_with_tokens["access_token"]),
        )
    assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_semantic_map_ai_service_non_200_returns_502(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    with patch(
        "src.api.v1.context_semantic.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=Response(status_code=500, text="boom")
        )
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = await async_client.get(
            "/api/v1/context/semantic-map?scope=personal",
            headers=_auth(test_user_with_tokens["access_token"]),
        )
    assert resp.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.asyncio
async def test_semantic_map_query_params_forwarded(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    body = _ok_map_response()
    captured: Dict[str, Any] = {}
    with patch(
        "src.api.v1.context_semantic.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()

        async def _capture(url, json):
            captured["json"] = json
            return _fake_response(200, body)

        mock_client.post = _capture
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = await async_client.get(
            "/api/v1/context/semantic-map?scope=personal&n_components=2&min_dist=0.3&min_cluster_size=10",
            headers=_auth(test_user_with_tokens["access_token"]),
        )
    assert resp.status_code == 200
    assert captured["json"]["n_components"] == 2
    assert captured["json"]["min_dist"] == 0.3
    assert captured["json"]["min_cluster_size"] == 10


# ─── /context/semantic-search ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_semantic_search_unauthenticated_returns_401(
    async_client: AsyncClient,
):
    resp = await async_client.post(
        "/api/v1/context/semantic-search",
        json={"query": "x", "scope": "personal"},
    )
    assert resp.status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    }


@pytest.mark.asyncio
async def test_semantic_search_empty_query_rejected(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    resp = await async_client.post(
        "/api/v1/context/semantic-search",
        json={"query": "   ", "scope": "personal"},
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    # Pydantic min_length=1 rejects pre-handler with 422; the strip
    # check inside the handler also returns 400. Either is correct
    # — we just don't want a silent 200.
    assert resp.status_code in {
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    }


@pytest.mark.asyncio
async def test_semantic_search_personal_scope_proxies(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    body = _ok_search_response()
    with patch(
        "src.api.v1.context_semantic.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_fake_response(200, body))
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = await async_client.post(
            "/api/v1/context/semantic-search",
            json={"query": "revenue", "scope": "personal", "top_k": 5},
            headers=_auth(test_user_with_tokens["access_token"]),
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["query"] == "revenue"
    assert len(data["hits"]) == 1
    assert data["hits"][0]["score"] == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_semantic_search_propagates_top_k_to_ai(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    body = _ok_search_response()
    captured: Dict[str, Any] = {}
    with patch(
        "src.api.v1.context_semantic.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()

        async def _capture(url, json):
            captured["json"] = json
            return _fake_response(200, body)

        mock_client.post = _capture
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = await async_client.post(
            "/api/v1/context/semantic-search",
            json={"query": "x", "scope": "personal", "top_k": 17},
            headers=_auth(test_user_with_tokens["access_token"]),
        )
    assert resp.status_code == 200
    assert captured["json"]["top_k"] == 17
    assert captured["json"]["query"] == "x"


@pytest.mark.asyncio
async def test_semantic_search_503_when_ai_unreachable(
    test_user_with_tokens: dict,
    async_client: AsyncClient,
):
    with patch(
        "src.api.v1.context_semantic.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectError("nope"))
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = await async_client.post(
            "/api/v1/context/semantic-search",
            json={"query": "anything", "scope": "personal"},
            headers=_auth(test_user_with_tokens["access_token"]),
        )
    assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
