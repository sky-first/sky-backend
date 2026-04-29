"""Ticket service.

RBAC summary:
  - **Create**: any authenticated user.
  - **List / Get**: reporter sees own; admin/owner sees all in their
    workspace; non-reporter non-admin denied.
  - **Update / Escalate / Assign**: admin / owner only.
  - **Comment**: reporter, admin, owner, or assignee.

Side-effects:
  - Every mutation appends a row to ``ticket_events`` (audit trail).
  - Escalation logs a structured warning so external pipes (Slack,
    PagerDuty) can pick it up. The actual webhook target is read from
    ``settings.TICKET_ESCALATION_WEBHOOK`` when set; otherwise we just
    log.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from src.models.ticket import (
    Ticket,
    TicketCategory,
    TicketEvent,
    TicketEventKind,
    TicketSeverity,
    TicketStatus,
)
from src.models.user import User
from src.schemas.ticket import (
    TicketCommentRequest,
    TicketCreateRequest,
    TicketDetailResponse,
    TicketEscalateRequest,
    TicketEventResponse,
    TicketListResponse,
    TicketResponse,
    TicketUpdateRequest,
)

logger = logging.getLogger(__name__)


_VALID_CATEGORIES = {c.value for c in TicketCategory}
_VALID_SEVERITIES = {s.value for s in TicketSeverity}
_VALID_STATUSES = {s.value for s in TicketStatus}


def _is_admin_like(user: User) -> bool:
    role = (user.role or "").lower()
    return role in {"admin", "owner"}


class TicketService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    #  Create
    # ------------------------------------------------------------------

    async def create(self, *, user: User, payload: TicketCreateRequest) -> TicketResponse:
        if payload.category not in _VALID_CATEGORIES:
            raise ValidationError(f"Unknown category: {payload.category}")
        if payload.severity not in _VALID_SEVERITIES:
            raise ValidationError(f"Unknown severity: {payload.severity}")

        ticket = Ticket(
            reporter_user_id=user.id,
            space_id=payload.space_id,
            subject=payload.subject.strip(),
            body=payload.body or "",
            category=payload.category,
            severity=payload.severity,
            status=TicketStatus.OPEN.value,
            context=dict(payload.context or {}),
        )
        self.db.add(ticket)
        await self.db.flush()

        await self._append_event(
            ticket_id=ticket.id,
            actor=user,
            kind=TicketEventKind.CREATED,
            payload={
                "subject": ticket.subject,
                "category": ticket.category,
                "severity": ticket.severity,
            },
        )
        await self.db.commit()
        await self.db.refresh(ticket)

        logger.info(
            "ticket_created id=%s reporter=%s severity=%s category=%s",
            ticket.id, user.id, ticket.severity, ticket.category,
        )

        # Best-effort Slack notification — fired AFTER the DB commit so a
        # webhook failure can't roll back the ticket. The DB is the
        # source of truth; the Slack ping is just a triage signal.
        await _post_slack_ticket_created(ticket=ticket, reporter=user)

        return TicketResponse.model_validate(ticket)

    # ------------------------------------------------------------------
    #  List / get
    # ------------------------------------------------------------------

    async def list(
        self,
        *,
        user: User,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> TicketListResponse:
        # Reporter sees own; admin/owner sees all.
        base = select(Ticket).where(Ticket.deleted_at.is_(None))
        if status:
            if status not in _VALID_STATUSES:
                raise ValidationError(f"Unknown status filter: {status}")
            base = base.where(Ticket.status == status)
        if not _is_admin_like(user):
            base = base.where(Ticket.reporter_user_id == user.id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        rows = (
            await self.db.execute(
                base.order_by(desc(Ticket.created_at)).offset(skip).limit(limit)
            )
        ).scalars().all()

        return TicketListResponse(
            items=[TicketResponse.model_validate(t) for t in rows],
            total=total,
        )

    async def get(self, *, user: User, ticket_id: UUID) -> TicketDetailResponse:
        ticket = await self._load_or_404(ticket_id)
        self._assert_can_view(ticket, user)

        events = (
            await self.db.execute(
                select(TicketEvent)
                .where(TicketEvent.ticket_id == ticket.id)
                .order_by(TicketEvent.created_at.asc())
            )
        ).scalars().all()

        detail = TicketDetailResponse.model_validate(ticket)
        detail = detail.model_copy(update={
            "events": [TicketEventResponse.model_validate(e) for e in events],
        })
        return detail

    # ------------------------------------------------------------------
    #  Update (admin/owner)
    # ------------------------------------------------------------------

    async def update(
        self,
        *,
        user: User,
        ticket_id: UUID,
        payload: TicketUpdateRequest,
    ) -> TicketResponse:
        ticket = await self._load_or_404(ticket_id)
        self._assert_can_admin(ticket, user)

        changed: Dict[str, Tuple[Any, Any]] = {}

        if payload.status is not None:
            if payload.status not in _VALID_STATUSES:
                raise ValidationError(f"Unknown status: {payload.status}")
            if payload.status != ticket.status:
                changed["status"] = (ticket.status, payload.status)
                ticket.status = payload.status

        if payload.severity is not None:
            if payload.severity not in _VALID_SEVERITIES:
                raise ValidationError(f"Unknown severity: {payload.severity}")
            if payload.severity != ticket.severity:
                changed["severity"] = (ticket.severity, payload.severity)
                ticket.severity = payload.severity

        if payload.assigned_to_user_id is not None and (
            payload.assigned_to_user_id != ticket.assigned_to_user_id
        ):
            changed["assigned_to_user_id"] = (
                str(ticket.assigned_to_user_id) if ticket.assigned_to_user_id else None,
                str(payload.assigned_to_user_id),
            )
            ticket.assigned_to_user_id = payload.assigned_to_user_id

        if payload.external_ref is not None and payload.external_ref != ticket.external_ref:
            changed["external_ref"] = (ticket.external_ref, payload.external_ref)
            ticket.external_ref = payload.external_ref

        if not changed:
            await self.db.commit()
            return TicketResponse.model_validate(ticket)

        # Emit one event per logical change (status / assigned have
        # dedicated kinds for the timeline UI).
        for field, (old, new) in changed.items():
            if field == "status":
                await self._append_event(
                    ticket_id=ticket.id, actor=user,
                    kind=TicketEventKind.STATUS_CHANGED,
                    payload={"from": old, "to": new},
                )
                if new == TicketStatus.RESOLVED.value:
                    await self._append_event(
                        ticket_id=ticket.id, actor=user,
                        kind=TicketEventKind.RESOLVED, payload={},
                    )
            elif field == "assigned_to_user_id":
                await self._append_event(
                    ticket_id=ticket.id, actor=user,
                    kind=TicketEventKind.ASSIGNED,
                    payload={"to": new},
                )
            else:
                await self._append_event(
                    ticket_id=ticket.id, actor=user,
                    kind=TicketEventKind.STATUS_CHANGED,
                    payload={"field": field, "from": old, "to": new},
                )

        await self.db.commit()
        await self.db.refresh(ticket)
        return TicketResponse.model_validate(ticket)

    # ------------------------------------------------------------------
    #  Comment
    # ------------------------------------------------------------------

    async def comment(
        self,
        *,
        user: User,
        ticket_id: UUID,
        payload: TicketCommentRequest,
    ) -> TicketEventResponse:
        ticket = await self._load_or_404(ticket_id)
        # Reporter, admin, owner, assignee can comment.
        if not (
            _is_admin_like(user)
            or ticket.reporter_user_id == user.id
            or ticket.assigned_to_user_id == user.id
        ):
            raise ForbiddenError("You can't comment on this ticket")

        event = await self._append_event(
            ticket_id=ticket.id,
            actor=user,
            kind=TicketEventKind.COMMENTED,
            payload={"body": payload.body.strip()},
        )
        await self.db.commit()
        return TicketEventResponse.model_validate(event)

    # ------------------------------------------------------------------
    #  Escalate
    # ------------------------------------------------------------------

    async def escalate(
        self,
        *,
        user: User,
        ticket_id: UUID,
        payload: TicketEscalateRequest,
    ) -> TicketResponse:
        ticket = await self._load_or_404(ticket_id)
        self._assert_can_admin(ticket, user)

        if ticket.status == TicketStatus.ESCALATED.value:
            return TicketResponse.model_validate(ticket)

        from datetime import datetime, timezone
        ticket.status = TicketStatus.ESCALATED.value
        ticket.escalated_at = datetime.now(timezone.utc)
        ticket.escalated_by_user_id = user.id

        await self._append_event(
            ticket_id=ticket.id,
            actor=user,
            kind=TicketEventKind.ESCALATED,
            payload={
                "note": (payload.note or "").strip(),
                "by": str(user.id),
            },
        )

        # Structured log line — external integrations (Slack webhook,
        # PagerDuty bridge) tail this. Exact field names match what the
        # Sky on-call tool expects (see runbook in
        # sky-security/INCIDENT_RESPONSE.md).
        logger.warning(
            "ticket_escalated ticket_id=%s reporter=%s severity=%s "
            "category=%s subject=%r escalated_by=%s note=%r",
            ticket.id, ticket.reporter_user_id, ticket.severity,
            ticket.category, ticket.subject, user.id,
            (payload.note or "")[:200],
        )

        await self.db.commit()
        await self.db.refresh(ticket)

        # Optional outbound webhook to the Sky on-call rotation. We fire
        # it AFTER the DB commit so an HTTP failure can't roll back the
        # escalation — the DB is the source of truth, the webhook is a
        # best-effort notification. Failures are swallowed and logged.
        await _post_escalation_webhook(ticket=ticket, actor=user, note=payload.note)

        return TicketResponse.model_validate(ticket)

    # ------------------------------------------------------------------
    #  Reopen
    # ------------------------------------------------------------------

    async def reopen(self, *, user: User, ticket_id: UUID) -> TicketResponse:
        ticket = await self._load_or_404(ticket_id)
        if not (
            _is_admin_like(user) or ticket.reporter_user_id == user.id
        ):
            raise ForbiddenError("You can't reopen this ticket")
        if ticket.status not in {TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value}:
            raise ValidationError("Only resolved/closed tickets can be reopened")

        prev = ticket.status
        ticket.status = TicketStatus.OPEN.value
        await self._append_event(
            ticket_id=ticket.id, actor=user, kind=TicketEventKind.REOPENED,
            payload={"from": prev},
        )
        await self.db.commit()
        await self.db.refresh(ticket)
        return TicketResponse.model_validate(ticket)

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------

    async def _load_or_404(self, ticket_id: UUID) -> Ticket:
        ticket = (
            await self.db.execute(
                select(Ticket).where(
                    Ticket.id == ticket_id,
                    Ticket.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not ticket:
            raise NotFoundError("Ticket not found")
        return ticket

    @staticmethod
    def _assert_can_view(ticket: Ticket, user: User) -> None:
        if _is_admin_like(user):
            return
        if ticket.reporter_user_id == user.id:
            return
        raise ForbiddenError("You can't view this ticket")

    @staticmethod
    def _assert_can_admin(ticket: Ticket, user: User) -> None:
        if not _is_admin_like(user):
            raise ForbiddenError("Only admin or owner can do this")

    async def _append_event(
        self,
        *,
        ticket_id: UUID,
        actor: Optional[User],
        kind: TicketEventKind,
        payload: Dict[str, Any],
    ) -> TicketEvent:
        event = TicketEvent(
            ticket_id=ticket_id,
            actor_user_id=actor.id if actor else None,
            kind=kind.value,
            payload=payload,
        )
        self.db.add(event)
        await self.db.flush()
        return event


# ─── Outbound Sky on-call webhook ────────────────────────────────────────


def _escalation_payload(ticket: Ticket, actor: User, note: Optional[str]) -> Dict[str, Any]:
    """The exact JSON contract the Sky on-call receiver pins on.

    Keep additions backwards-compatible (additive only) — the receiver
    in sky-security/INCIDENT_RESPONSE.md doesn't enforce a strict
    schema, but downstream alerting rules read these keys directly.
    """
    return {
        "event": "ticket_escalated",
        "ticket_id": str(ticket.id),
        "subject": ticket.subject,
        "category": ticket.category,
        "severity": ticket.severity,
        "status": ticket.status,
        "reporter_user_id": str(ticket.reporter_user_id),
        "escalated_by_user_id": str(actor.id),
        "escalated_by_email": actor.email,
        "note": (note or "").strip()[:1000],
        "external_ref": ticket.external_ref,
    }


async def _post_escalation_webhook(
    *,
    ticket: Ticket,
    actor: User,
    note: Optional[str],
) -> None:
    """Best-effort POST to the Sky on-call rotation. Swallows failures.

    The DB is already updated by the time we get here, so a webhook
    failure can't roll back the escalation. We log it loudly enough
    that ops will notice if the receiver is consistently down.
    """
    url = (settings.TICKET_ESCALATION_WEBHOOK_URL or "").strip()
    if not url:
        return  # log-only mode

    headers = {"Content-Type": "application/json"}
    if settings.TICKET_ESCALATION_WEBHOOK_TOKEN:
        headers["Authorization"] = f"Bearer {settings.TICKET_ESCALATION_WEBHOOK_TOKEN}"

    body = _escalation_payload(ticket, actor, note)

    try:
        async with httpx.AsyncClient(
            timeout=settings.TICKET_ESCALATION_WEBHOOK_TIMEOUT
        ) as client:
            resp = await client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            logger.error(
                "ticket_escalation_webhook_failed status=%s ticket_id=%s body=%r",
                resp.status_code, ticket.id, resp.text[:500],
            )
        else:
            logger.info(
                "ticket_escalation_webhook_delivered ticket_id=%s status=%s",
                ticket.id, resp.status_code,
            )
    except Exception as exc:  # noqa: BLE001 — webhook must not fail the request
        logger.exception(
            "ticket_escalation_webhook_error ticket_id=%s err=%s", ticket.id, exc
        )


# ─── Slack Incoming Webhook on ticket creation ───────────────────────────


_SEVERITY_EMOJI = {
    "low": ":information_source:",
    "medium": ":warning:",
    "high": ":rotating_light:",
    "critical": ":fire:",
}


def _slack_blocks_for_created(ticket: Ticket, reporter: User) -> Dict[str, Any]:
    """Slack block-kit payload for a newly-created ticket.

    Block-kit gives ops the structured fields (severity, category,
    reporter) on the left rail of the message instead of cramming
    everything into a single line of text.
    """
    severity = (ticket.severity or "").lower()
    emoji = _SEVERITY_EMOJI.get(severity, ":speech_balloon:")
    body_preview = (ticket.body or "").strip()
    if len(body_preview) > 500:
        body_preview = body_preview[:497] + "…"

    fields = [
        {"type": "mrkdwn", "text": f"*Severity*\n`{ticket.severity}`"},
        {"type": "mrkdwn", "text": f"*Category*\n`{ticket.category}`"},
        {"type": "mrkdwn", "text": f"*Reporter*\n{reporter.email or reporter.id}"},
        {"type": "mrkdwn", "text": f"*Status*\n`{ticket.status}`"},
    ]

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} New ticket: {ticket.subject[:140]}",
                "emoji": True,
            },
        },
        {"type": "section", "fields": fields},
    ]
    if body_preview:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f">>> {body_preview}"},
            }
        )

    app_url = (settings.APP_PUBLIC_URL or "").strip().rstrip("/")
    if app_url:
        deep_link = f"{app_url}/dashboard/settings/tickets/{ticket.id}"
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open ticket"},
                        "url": deep_link,
                        "style": "primary",
                    }
                ],
            }
        )

    return {
        "text": f"New ticket: {ticket.subject[:140]}",  # fallback for clients that don't render blocks
        "blocks": blocks,
    }


def _resolve_ticket_webhook_url(category: str) -> str:
    """Pick the right Slack webhook for a ticket's category.

    Routing (per Lucas's 3-channel strategy, 2026-04-29):
      bug             -> SLACK_TICKETS_WEBHOOK_URL   (#sky-tickets)
      feature_request -> SLACK_FEEDBACK_WEBHOOK_URL  (#sky-feedback)
      other           -> SLACK_FEEDBACK_WEBHOOK_URL  (#sky-feedback)

    If SLACK_FEEDBACK_WEBHOOK_URL is empty, non-bug tickets fall
    back to SLACK_TICKETS_WEBHOOK_URL — keeps the single-channel
    install working without forcing a second webhook config.
    """
    tickets = (settings.SLACK_TICKETS_WEBHOOK_URL or "").strip()
    feedback = (settings.SLACK_FEEDBACK_WEBHOOK_URL or "").strip()

    if (category or "").lower() == "bug":
        return tickets
    return feedback or tickets


async def _post_slack_ticket_created(*, ticket: Ticket, reporter: User) -> None:
    """Best-effort Slack POST. Failures are swallowed.

    Routes by ticket.category:
      bug → tickets channel; feature_request/other → feedback channel.
    Empty resolved URL = log-only mode (used by CI + local dev so we
    don't ping the real channels).
    """
    url = _resolve_ticket_webhook_url(ticket.category)
    if not url:
        return

    body = _slack_blocks_for_created(ticket, reporter)

    try:
        async with httpx.AsyncClient(
            timeout=settings.SLACK_TICKETS_WEBHOOK_TIMEOUT
        ) as client:
            resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            logger.error(
                "slack_ticket_webhook_failed status=%s category=%s ticket_id=%s body=%r",
                resp.status_code, ticket.category, ticket.id, resp.text[:500],
            )
        else:
            logger.info(
                "slack_ticket_webhook_delivered category=%s ticket_id=%s status=%s",
                ticket.category, ticket.id, resp.status_code,
            )
    except Exception as exc:  # noqa: BLE001 — webhook must not fail ticket creation
        logger.exception(
            "slack_ticket_webhook_error ticket_id=%s err=%s", ticket.id, exc
        )
