"""Sky-team auth guards + audit helpers for the Internal Console.

Two responsibilities:

* ``require_sky_team`` — FastAPI dependency that fails with 403 unless
  the current user is on the Sky engineering team. Acceptance criteria
  (any one of the three is enough):

    1. ``users.is_sky_operator = true`` on the platform DB. This is the
       canonical signal — production marks Lucas / Gustavo / Paulo here.
    2. The user's email matches ``CONSOLE_ALLOWED_EMAILS`` (env CSV).
       Used during onboarding before the column is populated.
    3. ``CONSOLE_DEV_BYPASS=true`` env var is set. Local-dev escape
       hatch so the developer running the stack doesn't need to seed
       the column first. **Refuses to take effect when
       ENVIRONMENT == "production"** — defence in depth.

* ``audit_action`` — helper that writes one row to
  ``internal_console_audit``. Always best-effort; if the audit insert
  fails the main action is not rolled back (we'd rather lose a log
  entry than refuse a destroy that already happened).

* ``audited`` — decorator factory wrapping route handlers. Records a
  success entry on return, a failure entry on exception. The
  decorated handler must accept ``request: Request`` and a DB session
  named ``db`` in its kwargs so the wrapper can pick the actor + DB.
"""

from __future__ import annotations

import functools
import logging
import os
import traceback
from typing import Any, Awaitable, Callable, Optional, TypeVar
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.config.settings import settings
from src.models.internal_console import (
    AuditAction,
    AuditResult,
    InternalConsoleAudit,
)
from src.models.user import User

logger = logging.getLogger(__name__)


# ── Sky-team guard ─────────────────────────────────────────────────


def _allowed_email_set() -> set[str]:
    raw = os.getenv("CONSOLE_ALLOWED_EMAILS") or ""
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def _dev_bypass_enabled() -> bool:
    if (settings.ENVIRONMENT or "").lower() == "production":
        return False
    return (os.getenv("CONSOLE_DEV_BYPASS") or "").lower() in {"true", "1", "yes", "on"}


def is_sky_team_member(user: User) -> bool:
    if getattr(user, "is_sky_operator", False):
        return True
    email = (user.email or "").lower()
    if email in _allowed_email_set():
        return True
    if _dev_bypass_enabled():
        return True
    return False


async def require_sky_team(
    user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency. Returns the user when allowed, else raises 403."""
    if not is_sky_team_member(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "sky_team_required",
                "detail": (
                    "This endpoint is restricted to SkyFirst engineering. "
                    "Contact your admin if you believe this is a mistake."
                ),
            },
        )
    return user


# ── Console role inference ─────────────────────────────────────────
# v1 has three roles: admin / operator / read_only. Until we wire a
# proper grant table the role is derived from settings.

_ADMIN_EMAILS_ENV = "CONSOLE_ADMIN_EMAILS"
_OPERATOR_EMAILS_ENV = "CONSOLE_OPERATOR_EMAILS"


def _env_email_set(var: str) -> set[str]:
    raw = os.getenv(var) or ""
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def role_for(user: User) -> str:
    email = (user.email or "").lower()
    if email in _env_email_set(_ADMIN_EMAILS_ENV):
        return "admin"
    if email in _env_email_set(_OPERATOR_EMAILS_ENV):
        return "operator"
    # Default Sky-team member starts at the lowest permission floor.
    return "read_only"


# ── Audit recording ────────────────────────────────────────────────


async def audit_action(
    db: AsyncSession,
    *,
    actor: User,
    action: AuditAction,
    tenant_slug: Optional[str],
    result: AuditResult,
    request_payload: Optional[dict[str, Any]] = None,
    result_details: Optional[dict[str, Any]] = None,
    actor_ip: Optional[str] = None,
) -> None:
    """Insert one row in ``internal_console_audit``.

    Failures are swallowed and logged — losing one audit entry is
    preferable to refusing a write the user explicitly asked for. If
    you need the audit insert to be a hard pre-condition, do not use
    this helper.
    """
    try:
        entry = InternalConsoleAudit(
            actor_email=actor.email,
            actor_ip=actor_ip,
            action=action.value,
            tenant_slug=tenant_slug,
            request_payload=request_payload,
            result=result.value,
            result_details=result_details,
        )
        db.add(entry)
        await db.flush()
    except Exception:
        logger.exception(
            "console_audit_write_failed",
            extra={
                "actor_email": actor.email,
                "action": action.value,
                "tenant_slug": tenant_slug,
                "result": result.value,
            },
        )


F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def audited(action: AuditAction, tenant_kwarg: str = "slug") -> Callable[[F], F]:
    """Decorator: record an audit entry per call.

    The decorated handler MUST accept the kwargs ``request: Request``,
    ``user: User`` (typically via Depends(require_sky_team)) and
    ``db: AsyncSession``. ``tenant_kwarg`` names the path/body
    parameter to capture as the audited ``tenant_slug``. When the
    parameter is missing the slug is recorded as ``None``.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Optional[Request] = kwargs.get("request")
            user: Optional[User] = kwargs.get("user")
            db: Optional[AsyncSession] = kwargs.get("db")
            slug = kwargs.get(tenant_kwarg)
            actor_ip = (
                request.client.host
                if request is not None and request.client is not None
                else None
            )
            payload = _safe_extract_payload(kwargs)

            try:
                result_value = await func(*args, **kwargs)
            except HTTPException as exc:
                if db is not None and user is not None:
                    await audit_action(
                        db,
                        actor=user,
                        action=action,
                        tenant_slug=str(slug) if slug is not None else None,
                        result=AuditResult.FAILURE,
                        request_payload=payload,
                        result_details={
                            "status_code": exc.status_code,
                            "detail": _stringify_detail(exc.detail),
                        },
                        actor_ip=actor_ip,
                    )
                raise
            except Exception as exc:  # noqa: BLE001
                if db is not None and user is not None:
                    await audit_action(
                        db,
                        actor=user,
                        action=action,
                        tenant_slug=str(slug) if slug is not None else None,
                        result=AuditResult.FAILURE,
                        request_payload=payload,
                        result_details={
                            "exception": type(exc).__name__,
                            "trace": traceback.format_exc()[-2000:],
                        },
                        actor_ip=actor_ip,
                    )
                raise

            if db is not None and user is not None:
                await audit_action(
                    db,
                    actor=user,
                    action=action,
                    tenant_slug=str(slug) if slug is not None else None,
                    result=AuditResult.SUCCESS,
                    request_payload=payload,
                    actor_ip=actor_ip,
                )
            return result_value

        return wrapper  # type: ignore[return-value]

    return decorator


# ── Helpers ────────────────────────────────────────────────────────


_REDACT_KEYS = {"password", "secret", "token", "authorization"}


def _safe_extract_payload(kwargs: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Pull the ``body`` parameter (if present) and redact sensitive keys."""
    payload = kwargs.get("payload") or kwargs.get("body")
    if payload is None:
        return None
    try:
        as_dict = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    except Exception:  # noqa: BLE001
        return None
    return {
        k: ("***REDACTED***" if k.lower() in _REDACT_KEYS else v)
        for k, v in as_dict.items()
    }


def _stringify_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    try:
        import json

        return json.dumps(detail)[:500]
    except Exception:  # noqa: BLE001
        return str(detail)[:500]


__all__ = [
    "audit_action",
    "audited",
    "is_sky_team_member",
    "require_sky_team",
    "role_for",
]
