import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_pillar(async_client: AsyncClient, test_user_with_tokens: dict):
    """Test creating a strategic pillar."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "name": "Innovation",
        "description": "Drive innovation across all products",
        "color": "#FF5733"
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
    pillar_res = await async_client.post("/api/v1/strategy/pillars", json=pillar_payload, headers=headers)
    pillar_id = pillar_res.json()["id"]
    
    # 2. Create objective linked to pillar
    obj_payload = {
        "pillar_id": pillar_id,
        "type": "corporate",
        "title": "Expand to Europe",
        "description": "Increase market share in EU",
        "horizon": "2026",
        "priority": "high"
    }
    
    response = await async_client.post("/api/v1/strategy/objectives", json=obj_payload, headers=headers)
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
    
    response = await async_client.get("/api/v1/strategy", headers=headers)
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
