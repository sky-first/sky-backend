#!/usr/bin/env python3
"""Print a devtools snippet that logs the browser in as a seeded RBAC
user for manual visual validation.

Local development only — uses the BE's own JWT secret to sign tokens
that the FE accepts as a normal session. Password login is disabled
in production, so this is the cleanest way to drop into a specific
RBAC persona without going through SSO.

Usage:
    python scripts/impersonate-rbac-user.py rbac.viewer-crewowner@example.com

Then paste the printed JS snippet into the browser devtools console
(http://localhost:3000) and refresh.
"""

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.security import create_access_token, create_refresh_token
from src.models.user import User


async def main(email: str) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            print(
                f"User {email!r} not found. Run scripts/seed-rbac-demo-users.py first.",
                file=sys.stderr,
            )
            sys.exit(1)

        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
        access_token = create_access_token(token_data, expires_delta=timedelta(hours=12))
        refresh_token = create_refresh_token(token_data)

    print()
    print(f"  → impersonating {email}  (role={user.role}, id={user.id})")
    print()
    print("  1. Open http://localhost:3000 in a fresh tab")
    print("  2. Open devtools console (Cmd+Opt+J)")
    print("  3. Paste:")
    print()
    print("─" * 78)
    print(
        f"localStorage.setItem('access_token', '{access_token}');\n"
        f"localStorage.setItem('refresh_token', '{refresh_token}');\n"
        f"location.href = '/dashboard';"
    )
    print("─" * 78)
    print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <email>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(main(sys.argv[1]))
