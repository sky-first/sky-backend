"""Ticket service tests.

QA perspectives — many roles, many edge cases:

A. Create — happy path + invalid category/severity/empty subject
B. List / get — reporter sees own; admin sees all; non-reporter blocked
C. Update — admin can change status/severity/assigned; non-admin
   denied; status transitions emit STATUS_CHANGED + RESOLVED.
D. Comment — reporter, admin, owner, assignee all allowed; outsider
   denied.
E. Escalate — admin only; emits ESCALATED event; idempotent (second
   call no-op); status flips to ESCALATED.
F. Reopen — reporter can reopen own; admin too; only from
   resolved/closed.
G. Audit trail — every mutation appends a TicketEvent; CREATED row
   present after creation.
H. Soft-delete — deleted tickets don't show up in list.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from src.models.ticket import Ticket, TicketEvent, TicketEventKind, TicketStatus
from src.models.user import User
from src.schemas.ticket import (
    TicketCommentRequest,
    TicketCreateRequest,
    TicketEscalateRequest,
    TicketUpdateRequest,
)
from src.services.ticket_service import TicketService


def _user(role: str = "user") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:6]}@x.test",
        name="t",
        password_hash="x",
        role=role,
    )


# ---------------------------------------------------------------------------
#  A — Create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreate:
    async def test_happy_path(self, db_session):
        u = _user()
        db_session.add(u)
        await db_session.flush()

        svc = TicketService(db_session)
        out = await svc.create(
            user=u,
            payload=TicketCreateRequest(
                subject="Chat returned 502",
                body="Tried to ask about Q1 sales, got CHAT_UPSTREAM_ERROR.",
                category="chat_error",
                severity="medium",
                context={"trace_id": "01HX", "endpoint": "/ai/chat"},
            ),
        )
        assert out.subject == "Chat returned 502"
        assert out.status == "open"
        assert out.context["trace_id"] == "01HX"

    async def test_unknown_category_rejected(self, db_session):
        u = _user()
        db_session.add(u)
        await db_session.flush()

        with pytest.raises(ValidationError):
            await TicketService(db_session).create(
                user=u,
                payload=TicketCreateRequest(
                    subject="x", body="y", category="does_not_exist",
                ),
            )

    async def test_unknown_severity_rejected(self, db_session):
        u = _user()
        db_session.add(u)
        await db_session.flush()

        with pytest.raises(ValidationError):
            await TicketService(db_session).create(
                user=u,
                payload=TicketCreateRequest(
                    subject="x", severity="catastrophic",
                ),
            )

    async def test_creates_audit_event(self, db_session):
        u = _user()
        db_session.add(u)
        await db_session.flush()

        out = await TicketService(db_session).create(
            user=u,
            payload=TicketCreateRequest(subject="x", body="y"),
        )

        events = (
            await db_session.execute(
                select(TicketEvent).where(TicketEvent.ticket_id == out.id)
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].kind == TicketEventKind.CREATED.value


# ---------------------------------------------------------------------------
#  B — List / get (RBAC)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRBAC:
    async def test_reporter_sees_own_only(self, db_session):
        alice = _user(role="user")
        bob = _user(role="user")
        db_session.add_all([alice, bob])
        await db_session.flush()

        svc = TicketService(db_session)
        await svc.create(user=alice, payload=TicketCreateRequest(subject="alice ticket"))
        await svc.create(user=bob, payload=TicketCreateRequest(subject="bob ticket"))

        result = await svc.list(user=alice)
        assert result.total == 1
        assert result.items[0].subject == "alice ticket"

    async def test_admin_sees_all(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        bob = _user(role="user")
        db_session.add_all([admin, alice, bob])
        await db_session.flush()

        svc = TicketService(db_session)
        await svc.create(user=alice, payload=TicketCreateRequest(subject="A"))
        await svc.create(user=bob, payload=TicketCreateRequest(subject="B"))

        result = await svc.list(user=admin)
        assert result.total == 2

    async def test_owner_sees_all(self, db_session):
        owner = _user(role="owner")
        alice = _user(role="user")
        db_session.add_all([owner, alice])
        await db_session.flush()

        svc = TicketService(db_session)
        await svc.create(user=alice, payload=TicketCreateRequest(subject="A"))

        result = await svc.list(user=owner)
        assert result.total == 1

    async def test_non_reporter_cannot_get_ticket(self, db_session):
        alice = _user(role="user")
        bob = _user(role="user")
        db_session.add_all([alice, bob])
        await db_session.flush()

        ticket = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )

        with pytest.raises(ForbiddenError):
            await TicketService(db_session).get(user=bob, ticket_id=ticket.id)

    async def test_admin_can_get_anyones_ticket(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        ticket = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        detail = await TicketService(db_session).get(user=admin, ticket_id=ticket.id)
        assert detail.id == ticket.id


# ---------------------------------------------------------------------------
#  C — Update (admin/owner only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdate:
    async def test_admin_can_change_status(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )

        out = await TicketService(db_session).update(
            user=admin,
            ticket_id=t.id,
            payload=TicketUpdateRequest(status="in_progress"),
        )
        assert out.status == "in_progress"

    async def test_status_to_resolved_emits_resolved_event(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        await TicketService(db_session).update(
            user=admin,
            ticket_id=t.id,
            payload=TicketUpdateRequest(status="resolved"),
        )

        kinds = [
            row[0]
            for row in await db_session.execute(
                select(TicketEvent.kind).where(TicketEvent.ticket_id == t.id)
            )
        ]
        assert TicketEventKind.RESOLVED.value in kinds
        assert TicketEventKind.STATUS_CHANGED.value in kinds

    async def test_non_admin_cannot_update(self, db_session):
        alice = _user(role="user")
        db_session.add(alice)
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        with pytest.raises(ForbiddenError):
            await TicketService(db_session).update(
                user=alice,
                ticket_id=t.id,
                payload=TicketUpdateRequest(status="resolved"),
            )

    async def test_unknown_status_rejected(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        with pytest.raises(ValidationError):
            await TicketService(db_session).update(
                user=admin,
                ticket_id=t.id,
                payload=TicketUpdateRequest(status="zombie"),
            )

    async def test_no_change_no_event(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        await TicketService(db_session).update(
            user=admin, ticket_id=t.id,
            payload=TicketUpdateRequest(status="open"),  # same as current
        )
        rows = (
            await db_session.execute(
                select(TicketEvent).where(TicketEvent.ticket_id == t.id)
            )
        ).scalars().all()
        # only the CREATED event
        assert len(rows) == 1


# ---------------------------------------------------------------------------
#  D — Comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestComment:
    async def test_reporter_can_comment(self, db_session):
        alice = _user(role="user")
        db_session.add(alice)
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        ev = await TicketService(db_session).comment(
            user=alice, ticket_id=t.id,
            payload=TicketCommentRequest(body="any update?"),
        )
        assert ev.kind == TicketEventKind.COMMENTED.value

    async def test_admin_can_comment(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        ev = await TicketService(db_session).comment(
            user=admin, ticket_id=t.id,
            payload=TicketCommentRequest(body="looking into it"),
        )
        assert ev.kind == TicketEventKind.COMMENTED.value

    async def test_outsider_cannot_comment(self, db_session):
        alice = _user(role="user")
        bob = _user(role="user")
        db_session.add_all([alice, bob])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        with pytest.raises(ForbiddenError):
            await TicketService(db_session).comment(
                user=bob, ticket_id=t.id,
                payload=TicketCommentRequest(body="hi"),
            )

    async def test_assignee_can_comment(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        bob = _user(role="user")
        db_session.add_all([admin, alice, bob])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        # Admin assigns Bob.
        await TicketService(db_session).update(
            user=admin, ticket_id=t.id,
            payload=TicketUpdateRequest(assigned_to_user_id=bob.id),
        )

        ev = await TicketService(db_session).comment(
            user=bob, ticket_id=t.id,
            payload=TicketCommentRequest(body="working on it"),
        )
        assert ev.kind == TicketEventKind.COMMENTED.value


# ---------------------------------------------------------------------------
#  E — Escalate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEscalate:
    async def test_admin_can_escalate(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        out = await TicketService(db_session).escalate(
            user=admin, ticket_id=t.id,
            payload=TicketEscalateRequest(note="customer impact P1"),
        )
        assert out.status == TicketStatus.ESCALATED.value
        assert out.escalated_at is not None
        assert out.escalated_by_user_id == admin.id

    async def test_non_admin_cannot_escalate(self, db_session):
        alice = _user(role="user")
        db_session.add(alice)
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        with pytest.raises(ForbiddenError):
            await TicketService(db_session).escalate(
                user=alice, ticket_id=t.id, payload=TicketEscalateRequest(),
            )

    async def test_escalate_idempotent(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        first = await TicketService(db_session).escalate(
            user=admin, ticket_id=t.id, payload=TicketEscalateRequest(),
        )
        second = await TicketService(db_session).escalate(
            user=admin, ticket_id=t.id, payload=TicketEscalateRequest(),
        )
        # Same escalated_at — second call no-op.
        assert first.escalated_at == second.escalated_at

    async def test_escalation_emits_event(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        await TicketService(db_session).escalate(
            user=admin, ticket_id=t.id,
            payload=TicketEscalateRequest(note="please look"),
        )

        kinds = [
            row[0] for row in await db_session.execute(
                select(TicketEvent.kind).where(TicketEvent.ticket_id == t.id)
            )
        ]
        assert TicketEventKind.ESCALATED.value in kinds


# ---------------------------------------------------------------------------
#  F — Reopen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReopen:
    async def test_reporter_can_reopen_own_resolved(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        db_session.add_all([admin, alice])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        await TicketService(db_session).update(
            user=admin, ticket_id=t.id,
            payload=TicketUpdateRequest(status="resolved"),
        )
        out = await TicketService(db_session).reopen(user=alice, ticket_id=t.id)
        assert out.status == TicketStatus.OPEN.value

    async def test_cant_reopen_open_ticket(self, db_session):
        alice = _user(role="user")
        db_session.add(alice)
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        with pytest.raises(ValidationError):
            await TicketService(db_session).reopen(user=alice, ticket_id=t.id)

    async def test_outsider_cannot_reopen(self, db_session):
        admin = _user(role="admin")
        alice = _user(role="user")
        bob = _user(role="user")
        db_session.add_all([admin, alice, bob])
        await db_session.flush()

        t = await TicketService(db_session).create(
            user=alice, payload=TicketCreateRequest(subject="A"),
        )
        await TicketService(db_session).update(
            user=admin, ticket_id=t.id,
            payload=TicketUpdateRequest(status="resolved"),
        )
        with pytest.raises(ForbiddenError):
            await TicketService(db_session).reopen(user=bob, ticket_id=t.id)


# ---------------------------------------------------------------------------
#  G — Audit trail snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_audit_trail(db_session):
    admin = _user(role="admin")
    alice = _user(role="user")
    db_session.add_all([admin, alice])
    await db_session.flush()

    svc = TicketService(db_session)
    t = await svc.create(user=alice, payload=TicketCreateRequest(subject="X"))
    await svc.comment(user=alice, ticket_id=t.id, payload=TicketCommentRequest(body="ping"))
    await svc.update(
        user=admin, ticket_id=t.id,
        payload=TicketUpdateRequest(status="in_progress"),
    )
    await svc.escalate(user=admin, ticket_id=t.id, payload=TicketEscalateRequest())
    await svc.update(
        user=admin, ticket_id=t.id,
        payload=TicketUpdateRequest(status="resolved"),
    )
    await svc.reopen(user=alice, ticket_id=t.id)

    detail = await svc.get(user=admin, ticket_id=t.id)
    kinds = [e.kind for e in detail.events]

    # We expect, in order:
    # CREATED, COMMENTED, STATUS_CHANGED (in_progress), ESCALATED,
    # STATUS_CHANGED (resolved), RESOLVED, REOPENED
    assert kinds[0] == "created"
    assert "commented" in kinds
    assert "status_changed" in kinds
    assert "escalated" in kinds
    assert "resolved" in kinds
    assert kinds[-1] == "reopened"


# ---------------------------------------------------------------------------
#  H — Soft-delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_deleted_ticket_not_in_list(db_session):
    from datetime import datetime, timezone

    admin = _user(role="admin")
    alice = _user(role="user")
    db_session.add_all([admin, alice])
    await db_session.flush()

    t = await TicketService(db_session).create(
        user=alice, payload=TicketCreateRequest(subject="A"),
    )
    raw = (
        await db_session.execute(select(Ticket).where(Ticket.id == t.id))
    ).scalar_one()
    raw.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    out = await TicketService(db_session).list(user=admin)
    assert all(item.id != t.id for item in out.items)

    with pytest.raises(NotFoundError):
        await TicketService(db_session).get(user=admin, ticket_id=t.id)
