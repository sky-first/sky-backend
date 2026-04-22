"""Unit tests for AuditService."""

import pytest
import uuid
import hashlib
import json
from src.services.audit_service import AuditService
from src.models.audit import AuditEvent

@pytest.mark.asyncio
async def test_log_event_creates_hash_chain(db_session):
    service = AuditService(db_session)
    
    # Log first event
    event1 = await service.log_event(
        actor_kind="user",
        actor_id=uuid.uuid4(),
        action="test.action.1",
        decision="allow"
    )
    assert event1.prev_hash is None
    assert event1.this_hash is not None

    # Log second event
    event2 = await service.log_event(
        actor_kind="user",
        actor_id=uuid.uuid4(),
        action="test.action.2",
        decision="deny"
    )
    assert event2.prev_hash == event1.this_hash
    assert event2.this_hash is not None
    assert event2.this_hash != event1.this_hash

@pytest.mark.asyncio
async def test_list_events_with_filters(db_session):
    service = AuditService(db_session)
    actor_id = uuid.uuid4()
    
    await service.log_event(actor_kind="user", actor_id=actor_id, action="action.a", decision="allow")
    await service.log_event(actor_kind="user", actor_id=actor_id, action="action.b", decision="deny")
    await service.log_event(actor_kind="system", action="action.a", decision="allow")

    # Filter by action
    result = await service.list_events(action="action.a")
    assert result["total"] == 2
    
    # Filter by actor_kind
    result = await service.list_events(actor_kind="system")
    assert result["total"] == 1
    
    # Filter by decision
    result = await service.list_events(decision="deny")
    assert result["total"] == 1

@pytest.mark.asyncio
async def test_verify_chain_detects_tampering(db_session):
    service = AuditService(db_session)
    
    await service.log_event(actor_kind="user", action="a1", decision="allow")
    await service.log_event(actor_kind="user", action="a2", decision="allow")
    await service.log_event(actor_kind="user", action="a3", decision="allow")

    # Verify intact chain
    verification = await service.verify_chain()
    assert verification["valid"] is True
    assert verification["checked"] == 3

    # Tamper with the middle event's hash
    from sqlalchemy import select
    res = await db_session.execute(select(AuditEvent).order_by(AuditEvent.id.asc()).offset(1).limit(1))
    event2 = res.scalar_one()
    event2.this_hash = "tampered_hash"
    await db_session.flush()

    # Verify broken chain
    verification = await service.verify_chain()
    assert verification["valid"] is False
    assert verification["checked"] == 2  # Breaks at index 2 (third event) because its prev_hash doesn't match
    assert verification["broken_at"] is not None

@pytest.mark.asyncio
async def test_verify_chain_empty(db_session):
    service = AuditService(db_session)
    verification = await service.verify_chain()
    assert verification["valid"] is True
    assert verification["checked"] == 0
