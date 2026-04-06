from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.tests.test_all_endpoints import create_test_page, get_auth_headers


@pytest.mark.asyncio
class TestIntelligenceSignalsEndpoints:
    """Tests for /api/v1/intelligence/signals endpoints."""

    async def test_list_signals_success(
        self,
        async_client: AsyncClient,
        test_user_with_tokens: dict,
        db_session: AsyncSession,
    ):
        """Test GET /api/v1/intelligence/signals - list signals."""
        user = test_user_with_tokens["user"]
        page = await create_test_page(db_session, user)
        headers = get_auth_headers(test_user_with_tokens["access_token"])

        # Create a test signal directly in DB for listing
        from src.models.intelligence_signal import IntelligenceSignal

        signal = IntelligenceSignal(
            id=uuid4(),  # type: ignore
            page_id=page.id,
            category="now",
            title="Test Signal",
            content="Test content",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(signal)
        await db_session.commit()

        response = await async_client.get(
            f"/api/v1/intelligence/signals/?page_id={page.id}", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["title"] == "Test Signal"

    async def test_create_signal_success(
        self,
        async_client: AsyncClient,
        test_user_with_tokens: dict,
        db_session: AsyncSession,
    ):
        """Test POST /api/v1/intelligence/signals/ - create signal."""
        user = test_user_with_tokens["user"]
        page = await create_test_page(db_session, user)
        headers = get_auth_headers(test_user_with_tokens["access_token"])

        payload = {
            "page_id": str(page.id),
            "category": "smart",
            "title": "New Smart Signal",
            "content": "Description of smart signal",
            "impact": "High",
            "confidence": 0.95,
        }

        response = await async_client.post(
            "/api/v1/intelligence/signals/", json=payload, headers=headers
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == payload["title"]
        assert data["category"] == payload["category"]
        assert "id" in data

    async def test_dismiss_signal_success(
        self,
        async_client: AsyncClient,
        test_user_with_tokens: dict,
        db_session: AsyncSession,
    ):
        """Test PATCH /api/v1/intelligence/signals/{id}/dismiss."""
        user = test_user_with_tokens["user"]
        page = await create_test_page(db_session, user)
        headers = get_auth_headers(test_user_with_tokens["access_token"])

        # Create a test signal
        from src.models.intelligence_signal import IntelligenceSignal

        signal = IntelligenceSignal(
            id=uuid4(),  # type: ignore
            page_id=page.id,
            category="explore",
            title="Dismiss Me",
            content="Content",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(signal)
        await db_session.commit()

        response = await async_client.patch(
            f"/api/v1/intelligence/signals/{signal.id}/dismiss", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_dismissed"] is not None

    async def test_delete_signal_success(
        self,
        async_client: AsyncClient,
        test_user_with_tokens: dict,
        db_session: AsyncSession,
    ):
        """Test DELETE /api/v1/intelligence/signals/{id}."""
        user = test_user_with_tokens["user"]
        page = await create_test_page(db_session, user)
        headers = get_auth_headers(test_user_with_tokens["access_token"])

        # Create a test signal
        from src.models.intelligence_signal import IntelligenceSignal

        signal = IntelligenceSignal(
            id=uuid4(),  # type: ignore
            page_id=page.id,
            category="now",
            title="Delete Me",
            content="Content",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(signal)
        await db_session.commit()

        response = await async_client.delete(
            f"/api/v1/intelligence/signals/{signal.id}", headers=headers
        )
        assert response.status_code == 204


@pytest.mark.asyncio
class TestSignalEventsEndpoints:
    """Tests for /api/v1/signal-events endpoints."""

    async def test_list_signal_events_success(
        self,
        async_client: AsyncClient,
        test_user_with_tokens: dict,
        db_session: AsyncSession,
    ):
        """Test GET /api/v1/signal-events/."""
        headers = get_auth_headers(test_user_with_tokens["access_token"])
        response = await async_client.get("/api/v1/signal-events/", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_create_signal_event_success(
        self,
        async_client: AsyncClient,
        test_user_with_tokens: dict,
        db_session: AsyncSession,
    ):
        """Test POST /api/v1/signal-events/."""
        headers = get_auth_headers(test_user_with_tokens["access_token"])
        payload = {
            "category": "INTERNAL",
            "sub_type": "Product Launch",
            "nature": "EVENT",
            "description": "Launch of the new AI module",
            "start_date": datetime.now(timezone.utc).isoformat(),
            "confidence": "HIGH",
        }
        response = await async_client.post("/api/v1/signal-events/", json=payload, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert data["sub_type"] == payload["sub_type"]
        assert "id" in data
