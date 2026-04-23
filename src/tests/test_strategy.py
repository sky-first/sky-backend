import pytest
from httpx import AsyncClient
from uuid import UUID, uuid4
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_create_pillar(async_client: AsyncClient, test_user_with_tokens: dict):
    """Test creating a strategic pillar."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "Innovation",
        "description": "Drive innovation across all products",
        "color": "#FF5733",
    }

    response = await async_client.post("/api/v1/strategy/pillars", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Innovation"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_objective(async_client: AsyncClient, test_user_with_tokens: dict):
    """Test creating a strategic objective."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create a pillar first
    pillar_payload = {"name": "Growth"}
    pillar_res = await async_client.post(
        "/api/v1/strategy/pillars", json=pillar_payload, headers=headers
    )
    pillar_id = pillar_res.json()["id"]

    # 2. Create objective linked to pillar
    obj_payload = {
        "pillar_id": pillar_id,
        "type": "corporate",
        "title": "Expand to Europe",
        "description": "Increase market share in EU",
        "horizon": "2026",
        "priority": "high",
    }

    response = await async_client.post(
        "/api/v1/strategy/objectives", json=obj_payload, headers=headers
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Expand to Europe"
    assert data["pillar_id"] == pillar_id


@pytest.mark.asyncio
async def test_get_strategy_tree(async_client: AsyncClient, test_user_with_tokens: dict):
    """Test fetching the full strategy tree."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create some data
    await async_client.post("/api/v1/strategy/pillars", json={"name": "P1"}, headers=headers)

    response = await async_client.get("/api/v1/strategy/tree", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "pillars" in data
    assert "objectives" in data
    assert len(data["pillars"]) >= 1


@pytest.mark.asyncio
async def test_get_strategy_health(async_client: AsyncClient, test_user_with_tokens: dict):
    """Test fetching strategy health metrics."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await async_client.get("/api/v1/strategy/health", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "coverage_percentage" in data
    assert "execution_gap" in data


@pytest.mark.asyncio
async def test_update_initiative_success(async_client: AsyncClient, test_user_with_tokens: dict):
    """Test updating a strategy initiative with real fields (Bug 1)."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create initiative
    init_payload = {"title": "New Initiative", "budget": 1000.0}
    res = await async_client.post(
        "/api/v1/strategy/initiatives", json=init_payload, headers=headers
    )
    init_id = res.json()["id"]

    # 2. Update initiative with new fields
    update_payload = {"title": "Updated Title", "budget": 5000.0, "impact": "High", "progress": 50}
    response = await async_client.put(
        f"/api/v1/strategy/initiatives/{init_id}", json=update_payload, headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["budget"] == 5000.0
    assert data["progress"] == 50


@pytest.mark.asyncio
async def test_update_assumption_success(async_client: AsyncClient, test_user_with_tokens: dict):
    """Test updating a strategy assumption with real fields (Bug 2)."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create assumption
    ass_payload = {"title": "Market Stable", "category": "Market"}
    res = await async_client.post("/api/v1/strategy/assumptions", json=ass_payload, headers=headers)
    ass_id = res.json()["id"]

    # 2. Update assumption
    update_payload = {"status": "validated", "impact_score": 5, "priority": "critical"}
    response = await async_client.put(
        f"/api/v1/strategy/assumptions/{ass_id}", json=update_payload, headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "validated"
    assert data["impact_score"] == 5


@pytest.mark.asyncio
async def test_create_signal_event_enum_uppercase(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Test creating a signal event with UPPERCASE enums (Bug 4)."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "category": "INTERNAL",
        "sub_type": "security",
        "nature": "SIGNAL",
        "description": "Critical security signal",
        "confidence": "HIGH",
        "start_date": "2026-03-18T12:00:00Z",
    }

    response = await async_client.post("/api/v1/signal-events/", json=payload, headers=headers)
    # If this returns 201, the Enum mismatch is solved.
    assert response.status_code == 201
    data = response.json()
    assert data["category"] == "INTERNAL"
    assert data["nature"] == "SIGNAL"


# ---------------------------------------------------------------------------
# Bug 6a phase 2 — Personal isolation on the strategy tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pillar_created_in_personal_mode_stamps_owner_and_nulls_space(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Creating a pillar with ?is_personal=true must persist owner_user_id
    and leave space_id/crew_id NULL so Personal stays isolated."""
    token = test_user_with_tokens["access_token"]
    user_id = str(test_user_with_tokens["user"].id)
    headers = {"Authorization": f"Bearer {token}"}

    res = await async_client.post(
        "/api/v1/strategy/pillars?is_personal=true",
        json={"name": "My Private Pillar"},
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["owner_user_id"] == user_id
    assert data["space_id"] is None
    assert data["crew_id"] is None


@pytest.mark.asyncio
async def test_pillar_created_in_space_leaves_owner_null(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Creating a pillar without is_personal (Space scope) must leave
    owner_user_id NULL so Space views can still see it."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = await async_client.post(
        "/api/v1/strategy/pillars",
        json={"name": "Team Pillar"},
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["owner_user_id"] is None


@pytest.mark.asyncio
async def test_strategy_tree_personal_only_returns_caller_items(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """GET /strategy/tree?is_personal=true must return only items the
    caller created in Personal; space-scoped items stay hidden."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # One Personal + one Space pillar, same caller.
    await async_client.post(
        "/api/v1/strategy/pillars?is_personal=true",
        json={"name": "Personal-only Pillar"},
        headers=headers,
    )
    await async_client.post(
        "/api/v1/strategy/pillars",
        json={"name": "Space-only Pillar"},
        headers=headers,
    )

    personal = await async_client.get(
        "/api/v1/strategy/tree?is_personal=true", headers=headers
    )
    assert personal.status_code == 200
    names = [p["name"] for p in personal.json()["pillars"]]
    assert "Personal-only Pillar" in names
    assert "Space-only Pillar" not in names


@pytest.mark.asyncio
async def test_strategy_tree_space_excludes_other_user_personal(
    async_client: AsyncClient,
    test_user_with_tokens: dict,
    test_second_user_with_tokens: dict,
):
    """Space/Crew view must NOT include another user's Personal items.
    This is the anti-leak check the whole isolation work hinges on."""
    # User B creates a Personal pillar that User A must never see in a
    # Space listing — even if the space_id coincides (we don't pass one).
    b_token = test_second_user_with_tokens["access_token"]
    b_headers = {"Authorization": f"Bearer {b_token}"}
    await async_client.post(
        "/api/v1/strategy/pillars?is_personal=true",
        json={"name": "B-private Pillar"},
        headers=b_headers,
    )

    a_token = test_user_with_tokens["access_token"]
    a_headers = {"Authorization": f"Bearer {a_token}"}
    res = await async_client.get("/api/v1/strategy/tree", headers=a_headers)
    assert res.status_code == 200
    names = [p["name"] for p in res.json()["pillars"]]
    assert "B-private Pillar" not in names



