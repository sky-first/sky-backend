"""One-off helper for the tenant-DB migration runbook.

Resolves a tenant's dedicated-DB SQLAlchemy URL from the platform
``tenant_registry`` (+ its AWS secret) using the app's own machinery, so
the migration can target the right DB without hand-assembling credentials.

Usage (inside a sky-be pod, where settings.DATABASE_URL = platform DB):

    python _tenant_migrate_helper.py url     # prints ONLY the tenant DB URL
    python _tenant_migrate_helper.py check   # read-only diagnosis, no URL leak

The slug defaults to ``gbtsolutions``; pass a different one as argv[2].
``check`` performs ONLY SELECTs — it never writes.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine


async def _resolve_url(slug: str) -> str:
    """Resolve the tenant's dedicated-DB URL straight from the registry row
    + its AWS secret. Deliberately does NOT depend on TenantContext /
    tenant_connection_manager internals (whose signature may differ between
    the deployed image and a local checkout) — it only reads the stable
    Tenant columns and mirrors _fetch_secret's two payload shapes.
    """
    import json
    from urllib.parse import quote_plus, unquote, urlparse

    from src.config.database import AsyncSessionLocal
    from src.models.tenant import Tenant

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one()
        host = row.db_host
        port = getattr(row, "db_port", None) or 5432
        name = row.db_name
        arn = row.db_credentials_secret_arn

    import boto3  # type: ignore[import-untyped]

    blob = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"])
    if "username" in blob and "password" in blob:
        user, pw = blob["username"], blob["password"]
    else:
        parsed = urlparse(blob["url"])
        user, pw = unquote(parsed.username or ""), unquote(parsed.password or "")
    return f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(pw)}@{host}:{port}/{name}"


async def _checks(slug: str) -> None:
    from src.config.database import prepare_async_db_url

    url = await _resolve_url(slug)
    cleaned, ssl_kwargs = prepare_async_db_url(url)
    eng = create_async_engine(cleaned, echo=False, connect_args=ssl_kwargs)
    async with eng.connect() as c:
        for tbl in ("alembic_version", "alembic_version_be"):
            exists = (
                await c.execute(
                    text(
                        "SELECT EXISTS(SELECT FROM information_schema.tables "
                        "WHERE table_name=:t)"
                    ),
                    {"t": tbl},
                )
            ).scalar()
            if exists:
                rows = list((await c.execute(text(f"SELECT version_num FROM {tbl}"))).scalars())
                print(f"{tbl}: {rows}")
            else:
                print(f"{tbl}: <table absent>")

        sess = (
            await c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='conversations' AND column_name='session_id'"
                )
            )
        ).first()
        print(f"conversations.session_id present: {bool(sess)}")

        cs = (await c.execute(text("SELECT to_regclass('public.chat_sessions')"))).scalar()
        print(f"chat_sessions table: {cs}")

        # Row counts that the backfill would touch (context only, read-only).
        conv_n = (await c.execute(text("SELECT count(*) FROM conversations"))).scalar()
        print(f"conversations rows: {conv_n}")
    await eng.dispose()


async def _upgrade(slug: str, target: str) -> int:
    """Run ``alembic upgrade <target>`` against the tenant DB as a fresh
    subprocess with ``DATABASE_URL`` set to the resolved tenant URL — exactly
    how the platform Migrate Job runs it. The URL lives only in the child's
    env (never printed). Returns the alembic exit code.
    """
    import os
    import subprocess

    url = await _resolve_url(slug)
    env = {**os.environ, "DATABASE_URL": url}
    proc = subprocess.run(
        ["alembic", "upgrade", target],
        cwd="/app",
        env=env,
    )
    return proc.returncode


async def _main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    slug = sys.argv[2] if len(sys.argv) > 2 else "gbtsolutions"
    if cmd == "url":
        print(await _resolve_url(slug))
    elif cmd == "upgrade":
        # Optional explicit target (e.g. a specific revision); default head.
        target = sys.argv[3] if len(sys.argv) > 3 else "head"
        sys.exit(await _upgrade(slug, target))
    else:
        await _checks(slug)


if __name__ == "__main__":
    asyncio.run(_main())
