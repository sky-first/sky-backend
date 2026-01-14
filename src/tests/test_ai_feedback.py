"""Tests for AI feedback endpoint."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ai import AIFeedback, AIQuery
from src.repositories.base import BaseRepository


def get_auth_headers(access_token: str) -> dict:
    """Get authorization headers."""
    return {"Authorization": f"Bearer {access_token}"}


async def create_test_query(db_session: AsyncSession, user_id):
    """Helper to create a test AI query."""
    query_repo = BaseRepository(db_session, AIQuery)
    now = datetime.now(timezone.utc)
    query = await query_repo.create(
        user_id=user_id,
        question="How many users?",
        answer="There are 10 users.",
        status="completed",
        configure_data={"question": "How many users?", "knowledge": []},
        created_at=now,
        updated_at=now,
    )
    await db_session.commit()
    await db_session.refresh(query)
    return query


class TestAIFeedback:
    @pytest.mark.asyncio
    async def test_submit_feedback_success(
        self, client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        """Test POST /api/v1/ai/feedback - create and update."""
        user = test_user_with_tokens["user"]
        query = await create_test_query(db_session, user.id)
        headers = get_auth_headers(test_user_with_tokens["access_token"])

        # 1. Create 'good' feedback
        fb_data = {"query_id": str(query.id), "feedback": "good"}
        response = client.post("/api/v1/ai/feedback", json=fb_data, headers=headers)
        assert response.status_code == 200
        assert response.json()["message"] == "Feedback submitted successfully"

        # Verify in DB
        from sqlalchemy import select

        res = await db_session.execute(
            select(AIFeedback).where(AIFeedback.query_id == query.id, AIFeedback.user_id == user.id)
        )
        row = res.scalar_one_or_none()
        assert row is not None
        assert row.rating == "good"
        assert row.comment is None

        # 2. Update to 'bad' with comment (upsert)
        fb_update = {
            "query_id": str(query.id),
            "feedback": "bad",
            "comment": "The count is actually 12.",
        }
        response = client.post("/api/v1/ai/feedback", json=fb_update, headers=headers)
        assert response.status_code == 200

        # Verify update in DB
        res = await db_session.execute(
            select(AIFeedback).where(AIFeedback.query_id == query.id, AIFeedback.user_id == user.id)
        )
        row = res.scalar_one_or_none()
        assert row is not None
        assert row.rating == "bad"
        assert row.comment == "The count is actually 12."

    @pytest.mark.asyncio
    async def test_submit_feedback_ownership_validation(
        self, client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        """Test POST /api/v1/ai/feedback - cannot give feedback on other user's query."""
        # Create query for a different user
        other_user_id = uuid4()
        query = await create_test_query(db_session, other_user_id)

        headers = get_auth_headers(test_user_with_tokens["access_token"])
        fb_data = {"query_id": str(query.id), "feedback": "good"}
        response = client.post("/api/v1/ai/feedback", json=fb_data, headers=headers)
        # Should return 404 (NotFoundError) as per implementation
        assert response.status_code == 404

    def test_submit_feedback_invalid_rating(self, client: TestClient, test_user_with_tokens: dict):
        """Test POST /api/v1/ai/feedback - invalid rating enum."""
        headers = get_auth_headers(test_user_with_tokens["access_token"])
        fb_data = {"query_id": str(uuid4()), "feedback": "not_good_or_bad"}
        response = client.post("/api/v1/ai/feedback", json=fb_data, headers=headers)
        assert response.status_code == 422

    def test_submit_feedback_deprecated_message_id(
        self, client: TestClient, test_user_with_tokens: dict
    ):
        """Test POST /api/v1/ai/feedback - deprecated flow still returns 200 (but does nothing)."""
        headers = get_auth_headers(test_user_with_tokens["access_token"])
        fb_data = {"message_id": "msg-123", "feedback": "good"}
        response = client.post("/api/v1/ai/feedback", json=fb_data, headers=headers)
        assert response.status_code == 200
        assert response.json()["message"] == "Feedback submitted successfully"
