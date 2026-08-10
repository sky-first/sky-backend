"""BE-07 slice · voice session persistence (T-07.8).

A finished voice transcript is persisted server-side as a Conversation with
origin='voice' messages, so it appears in History and reopens as a transcript.
"""

from __future__ import annotations

import uuid

import pytest

from src.models.page import Page
from src.tests.acceptance_helpers import assert_auth_matrix, bearer


async def _make_page(db, owner_id) -> uuid.UUID:
    pid = uuid.uuid4()
    db.add(Page(id=pid, name="Chats", type="personal", color="#FAB721", owner_id=owner_id))
    await db.commit()
    return pid


@pytest.mark.asyncio
async def test_voice_session_persists_and_shows_as_voice(
    async_client, test_user, valid_access_token, db_session
):
    page_id = await _make_page(db_session, test_user["user"].id)

    r = await async_client.post(
        "/api/v1/voice/sessions",
        json={
            "page_id": str(page_id),
            "duration_ms": 42000,
            "turns": [
                {"role": "user", "text": "why did north sales drop?"},
                {"role": "sky", "text": "Three clients lapsed — about €24k of Q2."},
            ],
        },
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 201
    assert r.json()["message_count"] == 2

    # It appears in History as a VOICE conversation (BE-04 origin derivation).
    r2 = await async_client.get(
        f"/api/v1/pages/{page_id}/conversations", headers=bearer(valid_access_token)
    )
    items = r2.json()["items"]
    assert any(c["origin"] == "voice" and c["title"] == "why did north sales drop?" for c in items)


@pytest.mark.asyncio
async def test_voice_session_on_foreign_page_is_404(async_client, valid_access_token, db_session):
    # A page the caller does not own → 404 (no existence leak).
    other = uuid.uuid4()  # never created / not the caller's
    r = await async_client.post(
        "/api/v1/voice/sessions",
        json={"page_id": str(other), "turns": [{"role": "user", "text": "hi"}]},
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_voice_session_auth_matrix(async_client, expired_token, invalid_token):
    await assert_auth_matrix(
        async_client,
        "POST",
        "/api/v1/voice/sessions",
        expired_token=expired_token,
        invalid_token=invalid_token,
        json={"page_id": str(uuid.uuid4()), "turns": [{"role": "user", "text": "hi"}]},
    )


@pytest.mark.asyncio
async def test_voice_session_appends_to_existing_conversation(
    async_client, test_user, valid_access_token, db_session
):
    """Voice asked inside an open chat threads into it, not a new conversation."""
    page_id = await _make_page(db_session, test_user["user"].id)
    hdr = bearer(valid_access_token)

    r1 = await async_client.post(
        "/api/v1/voice/sessions",
        json={
            "page_id": str(page_id),
            "duration_ms": 1000,
            "turns": [
                {"role": "user", "text": "how many clients?"},
                {"role": "sky", "text": "374 clients."},
            ],
        },
        headers=hdr,
    )
    assert r1.status_code == 201
    conv_id = r1.json()["conversation_id"]

    # A follow-up spoken turn threaded into the SAME conversation.
    r2 = await async_client.post(
        "/api/v1/voice/sessions",
        json={
            "page_id": str(page_id),
            "duration_ms": 1000,
            "conversation_id": conv_id,
            "turns": [
                {"role": "user", "text": "and invoices?"},
                {"role": "sky", "text": "128 invoices."},
            ],
        },
        headers=hdr,
    )
    assert r2.status_code == 201
    assert r2.json()["conversation_id"] == conv_id  # appended, not a new thread

    # The thread now holds all four turns, in order.
    rmsg = await async_client.get(
        f"/api/v1/conversations/{conv_id}/messages", headers=hdr
    )
    contents = [m["content"] for m in rmsg.json()["items"]]
    assert contents == [
        "how many clients?",
        "374 clients.",
        "and invoices?",
        "128 invoices.",
    ]

    # And only ONE conversation exists on the page.
    rconv = await async_client.get(
        f"/api/v1/pages/{page_id}/conversations", headers=hdr
    )
    assert len(rconv.json()["items"]) == 1
