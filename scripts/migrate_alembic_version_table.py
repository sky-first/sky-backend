"""Migrate sky-be's alembic head from the legacy shared ``alembic_version``
table to the new dedicated ``alembic_version_be`` table.

Runs ONCE per environment before the first deploy that ships
``migrations/env.py`` with ``version_table="alembic_version_be"``.
After this script, sky-be writes/reads ``alembic_version_be`` and
sky-ai keeps using the legacy ``alembic_version`` — see the
``skyfirst-alembic-version-conflict`` memory for the back-story.

Idempotent: re-running is safe — it only inserts the row when
``alembic_version_be`` is empty.

Usage::

    # local dev (Docker Compose)
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db \\
        venv/Scripts/python.exe scripts/migrate_alembic_version_table.py

    # staging (from inside a sky-be pod with kubeconfig + env wired)
    python scripts/migrate_alembic_version_table.py --expected-head <REV>

The script does:

  1. Confirm the legacy ``alembic_version`` table exists.
  2. Pick the row that matches a known sky-be revision (from the
     local script tree). Sky-ai rows are ignored.
  3. CREATE TABLE ``alembic_version_be`` (if not present) with the
     same schema.
  4. INSERT the picked row if the new table is empty.
  5. Print a summary.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from src.config.database import prepare_async_db_url  # noqa: E402


def _local_sky_be_revisions() -> Set[str]:
    """Collect every revision ID known to this checkout."""
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    return {rev.revision for rev in script.walk_revisions()}


async def main(expected_head: Optional[str]) -> int:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL env var required", file=sys.stderr)
        return 2

    # asyncpg rejects ``sslmode`` as a kwarg; strip it to ``ssl`` in
    # connect_args. See ``src.config.database.prepare_async_db_url``.
    cleaned_url, ssl_kwargs = prepare_async_db_url(db_url)
    engine = create_async_engine(
        cleaned_url, echo=False, connect_args=ssl_kwargs
    )
    sky_be_revs = _local_sky_be_revisions()
    print(f"  loaded {len(sky_be_revs)} sky-be revisions from script tree")

    async with engine.begin() as conn:
        legacy_exists = (
            await conn.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT FROM information_schema.tables "
                    "WHERE table_name = 'alembic_version')"
                )
            )
        ).scalar()
        if not legacy_exists:
            print("  no legacy alembic_version table present — nothing to migrate")
            await engine.dispose()
            return 0

        # Read all rows from legacy table.
        rows: List[str] = list(
            (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalars()
        )
        print(f"  legacy alembic_version contains {len(rows)} row(s): {rows}")

        # Identify the sky-be row.
        sky_be_rows = [r for r in rows if r in sky_be_revs]
        sky_ai_rows = [r for r in rows if r not in sky_be_revs]
        print(f"  classified: {len(sky_be_rows)} sky-be · {len(sky_ai_rows)} other")

        if not sky_be_rows:
            print(
                "  no sky-be revision in legacy table — using ``expected_head`` "
                "argument if provided, else aborting"
            )
            if not expected_head:
                print("  pass --expected-head <REV> to seed the new table", file=sys.stderr)
                await engine.dispose()
                return 1
            picked = expected_head
        elif len(sky_be_rows) == 1:
            picked = sky_be_rows[0]
        else:
            # Pick the latest head — rare unless someone manually
            # double-inserted. Print warning.
            print(
                f"  WARNING multiple sky-be rows in legacy table: {sky_be_rows} — "
                f"picking {sky_be_rows[-1]}"
            )
            picked = sky_be_rows[-1]

        if expected_head and picked != expected_head:
            print(
                f"  WARNING expected_head={expected_head} but picking {picked}",
                file=sys.stderr,
            )

        # Ensure new table exists.
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version_be ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_be_pkc PRIMARY KEY (version_num))"
            )
        )

        # Seed if empty.
        already = (
            await conn.execute(
                text("SELECT version_num FROM alembic_version_be")
            )
        ).scalar_one_or_none()
        if already:
            print(f"  alembic_version_be already populated with {already!r} — no-op")
        else:
            await conn.execute(
                text("INSERT INTO alembic_version_be (version_num) VALUES (:v)"),
                {"v": picked},
            )
            print(f"  inserted {picked!r} into alembic_version_be")

        # Optionally clean the legacy table — only remove sky-be rows;
        # leave sky-ai's untouched.
        if sky_be_rows:
            await conn.execute(
                text(
                    "DELETE FROM alembic_version "
                    "WHERE version_num = ANY(:revs)"
                ),
                {"revs": sky_be_rows},
            )
            print(f"  removed {len(sky_be_rows)} sky-be row(s) from legacy table")

    await engine.dispose()
    print("done.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-head",
        default=None,
        help=(
            "Fallback revision to seed alembic_version_be when no sky-be "
            "revision is found in the legacy table (greenfield environment)."
        ),
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.expected_head)))
