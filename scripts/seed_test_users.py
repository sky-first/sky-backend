"""Seed one user per platform role so impersonation / RBAC flows can be
validated end-to-end without needing to sign-up multiple Google accounts.

Idempotent: rerunning only inserts missing rows (match on email).

Passwords are all `Test1234!` — good enough for a local dev stack and
explicitly NOT acceptable for any environment that faces real users.

Usage:
    cd sky-poc-backend
    source venv/bin/activate
    python scripts/seed_test_users.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select

from src.config.database import AsyncSessionLocal
from src.core.security import get_password_hash
from src.models.user import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed_test_users")


DEFAULT_PASSWORD = "Test1234!"
EMAIL_DOMAIN = "sky.local"


# Every platform role that exists in the RBAC catalogue. Keep this list
# in sync with `src/lib/rbac/platform-roles.ts` on the frontend — when a
# new role lands there, add a seed row here too.
TEST_USERS: list[tuple[str, str, str]] = [
    # (display name, role, short purpose)
    ("Alice Owner", "owner", "Tenant founder — sees everything including owner-exclusive perms"),
    ("Bruno Admin", "admin", "Platform admin — full access minus owner-exclusive perms"),
    ("Clara Commander", "commander", "Crew admin — manages members + content inside a Crew"),
    ("Diego Navigator", "navigator", "Senior contributor — can edit content, no member management"),
    ("Elena Explorer", "explorer", "Default new-user role — views + queries, limited edits"),
    ("Fabio Guest", "guest", "Read-only Crew member — internal stakeholder access"),
    ("Gina BillingAdmin", "billing_admin", "Billing-only admin — plan / usage / invoices"),
    ("Hugo Compliance", "compliance_auditor", "Read-only audit access + permission matrix export"),
    ("Iris Service", "service_account", "Non-human integration — API-only, no chat / notifications"),
    ("Joana Member", "member", "Legacy member role — kept for backward compatibility tests"),
    ("Kai Viewer", "viewer", "Legacy read-only role — kept for backward compatibility tests"),
]


def _email(name: str) -> str:
    first = name.split()[0].lower()
    return f"{first}@{EMAIL_DOMAIN}"


async def _upsert(session, name: str, role: str, note: str) -> str:
    email = _email(name)
    stmt = select(User).where(User.email == email)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        # Normalise the role in case an earlier seed used a different value.
        if existing.role != role:
            existing.role = role
            logger.info("  updated role on %s → %s", email, role)
            return "updated"
        return "exists"
    session.add(
        User(
            id=uuid.uuid4(),
            email=email,
            name=name,
            role=role,
            password_hash=get_password_hash(DEFAULT_PASSWORD),
            email_verified=True,
            email_verified_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    logger.info("  inserted %-30s role=%s — %s", email, role, note)
    return "inserted"


async def main() -> int:
    async with AsyncSessionLocal() as session:
        counts: dict[str, int] = {"inserted": 0, "updated": 0, "exists": 0}
        for name, role, note in TEST_USERS:
            result = await _upsert(session, name, role, note)
            counts[result] = counts.get(result, 0) + 1
        await session.commit()
    logger.info("Done — %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
    logger.info("Every test user signs in with password: %s", DEFAULT_PASSWORD)
    logger.info("Emails follow the pattern <firstname>@%s", EMAIL_DOMAIN)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
