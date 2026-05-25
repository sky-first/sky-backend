#!/usr/bin/env python3
"""Reset tenant data so a first-time user experience can be tested.

DESTRUCTIVE — truncates spaces, crews, connections, agents, pages,
dashboards, widgets, findings, insights, and related assoc tables. Users
table and auth tokens are kept so you stay logged in.

Usage (from sky-poc-backend root, with venv activated):
    python scripts/reset_to_first_user.py --keep-email <your@email>

If --keep-email is omitted, every user survives but all their tenant
data goes. If --yes is omitted, the script asks for interactive
confirmation.

What gets truncated (in dependency order, CASCADE where possible):
    agent_findings, agent_executions, agents
    widgets, dashboards
    pages
    space_tables, space_connections, space_members, spaces
    crew_members, crews
    insight_approvals, insights
    ai_history, ai_queries, conversations
    enterprise_relationships
    glossary_terms
    data_connections

Non-destructive:
    users, refresh_tokens, audit_log, platform_role_grants
"""

import argparse
import asyncio
import os
import sys
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


TRUNCATE_TABLES = [
    # Order matters when using plain TRUNCATE without CASCADE on
    # non-PostgreSQL backends. We pass CASCADE below so order is mostly
    # for documentation.
    "agent_findings",
    "agent_executions",
    "agents",
    "widgets",
    "dashboards",
    "pages",
    "space_tables",
    "space_connections",
    "space_members",
    "spaces",
    "crew_members",
    "crews",
    "insight_approvals",
    "insights",
    "ai_history",
    "ai_queries",
    "conversations",
    "enterprise_relationships",
    "glossary_terms",
    "data_connections",
]


async def reset(keep_email: Optional[str]) -> None:
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "postgres")
    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_port = os.getenv("POSTGRES_PORT", "5433")
    pg_db = os.getenv("POSTGRES_DB", "sky_platform_db")

    url = f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        # Discover which tables actually exist — the list covers multiple
        # schema generations, so silently skip anything that isn't here.
        present = {
            row[0]
            for row in (await conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            ))).fetchall()
        }

        to_truncate = [t for t in TRUNCATE_TABLES if t in present]
        missing = [t for t in TRUNCATE_TABLES if t not in present]
        if missing:
            print(f"Skipping (not in DB): {', '.join(missing)}")

        if not to_truncate:
            print("No eligible tables found — is the DB bootstrapped?")
            return

        joined = ", ".join(to_truncate)
        print(f"Truncating: {joined}")
        await conn.execute(text(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE"))

        # Optional: remove users OTHER than the kept one so you can
        # truly test "first login" state.
        if keep_email:
            deleted = await conn.execute(
                text("DELETE FROM users WHERE email != :kept"),
                {"kept": keep_email},
            )
            print(f"Removed {deleted.rowcount} users — kept only {keep_email}")
            # Clear the refresh tokens of the deleted users (cascade may
            # already handle this, but be explicit in case FK wasn't set).
            await conn.execute(text(
                "DELETE FROM refresh_tokens WHERE user_id NOT IN "
                "(SELECT id FROM users)"
            ))

    await engine.dispose()
    print("✅ Reset complete.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Reset tenant data for first-user testing.")
    ap.add_argument("--keep-email", help="If set, delete every user except this one. Otherwise, users are kept as-is.")
    ap.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = ap.parse_args()

    if not args.yes:
        print("This will TRUNCATE tenant data in the sky backend DB.")
        print("Spaces, crews, connections, agents, findings, pages, dashboards — all gone.")
        print("Users stay unless you pass --keep-email.")
        reply = input("Type 'reset' to confirm: ")
        if reply.strip().lower() != "reset":
            print("Aborted.")
            return 1

    asyncio.run(reset(args.keep_email))
    return 0


if __name__ == "__main__":
    sys.exit(main())
