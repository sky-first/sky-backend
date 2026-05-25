"""Audit service — writes immutable audit events with hash chain.

Every authorization decision (allow and deny) is recorded here. The hash chain
makes it possible to detect tampering: if any row is modified or deleted, the
chain breaks and the integrity check fails.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit import AuditEvent

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_event(
        self,
        *,
        actor_kind: str,
        actor_id: Optional[UUID] = None,
        actor_email: Optional[str] = None,
        action: str,
        resource_kind: Optional[str] = None,
        resource_id: Optional[str] = None,
        decision: str,
        decision_reason: Optional[str] = None,
        request_id: Optional[UUID] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        sky_session_id: Optional[UUID] = None,
        sky_ticket_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Write a single audit event with hash chain link."""
        # Get the previous hash (from the last row)
        result = await self.db.execute(
            select(AuditEvent.this_hash)
            .order_by(AuditEvent.id.desc())
            .limit(1)
        )
        prev_hash = result.scalar_one_or_none()

        # Compute this_hash = sha256(prev_hash + actor + action + decision + resource)
        chain_data = json.dumps({
            "prev": prev_hash or "",
            "actor_kind": actor_kind,
            "actor_id": str(actor_id) if actor_id else "",
            "action": action,
            "decision": decision,
            "resource_kind": resource_kind or "",
            "resource_id": resource_id or "",
        }, sort_keys=True)
        this_hash = hashlib.sha256(chain_data.encode()).hexdigest()

        event = AuditEvent(
            actor_kind=actor_kind,
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,
            resource_kind=resource_kind,
            resource_id=resource_id,
            decision=decision,
            decision_reason=decision_reason,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
            sky_session_id=sky_session_id,
            sky_ticket_id=sky_ticket_id,
            extra_data=metadata,
            prev_hash=prev_hash,
            this_hash=this_hash,
        )
        self.db.add(event)
        # Don't commit here — let the caller's transaction handle it.
        # For fire-and-forget audit, the caller can flush.
        try:
            await self.db.flush()
        except Exception as exc:
            # Audit write failure must NEVER block the request.
            logger.error("audit.write_failed action=%s error=%s", action, exc)

        return event

    async def list_events(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        action: Optional[str] = None,
        actor_kind: Optional[str] = None,
        actor_id: Optional[UUID] = None,
        decision: Optional[str] = None,
        resource_kind: Optional[str] = None,
        resource_id: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Paginated list of audit events with optional filters."""
        query = select(AuditEvent)

        if action:
            query = query.where(AuditEvent.action == action)
        if actor_kind:
            query = query.where(AuditEvent.actor_kind == actor_kind)
        if actor_id:
            query = query.where(AuditEvent.actor_id == actor_id)
        if decision:
            query = query.where(AuditEvent.decision == decision)
        if resource_kind:
            query = query.where(AuditEvent.resource_kind == resource_kind)
        if resource_id:
            query = query.where(AuditEvent.resource_id == resource_id)

        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        # Fetch
        query = query.order_by(AuditEvent.occurred_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        events = result.scalars().all()

        return {
            "items": [
                {
                    "id": e.id,
                    "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                    "actor_kind": e.actor_kind,
                    "actor_id": str(e.actor_id) if e.actor_id else None,
                    "actor_email": e.actor_email,
                    "action": e.action,
                    "resource_kind": e.resource_kind,
                    "resource_id": e.resource_id,
                    "decision": e.decision,
                    "decision_reason": e.decision_reason,
                    "request_id": str(e.request_id) if e.request_id else None,
                    "metadata": e.extra_data,
                    "prev_hash": e.prev_hash,
                    "this_hash": e.this_hash,
                }
                for e in events
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def verify_chain(self, limit: int = 1000) -> Dict[str, Any]:
        """Verify the hash chain integrity for the last N events."""
        result = await self.db.execute(
            select(AuditEvent).order_by(AuditEvent.id.asc()).limit(limit)
        )
        events = result.scalars().all()

        if not events:
            return {"valid": True, "checked": 0, "broken_at": None}

        for i in range(1, len(events)):
            if events[i].prev_hash != events[i - 1].this_hash:
                return {
                    "valid": False,
                    "checked": i,
                    "broken_at": events[i].id,
                    "expected_prev": events[i - 1].this_hash,
                    "actual_prev": events[i].prev_hash,
                }

        return {"valid": True, "checked": len(events), "broken_at": None}
