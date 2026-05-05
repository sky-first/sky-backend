"""One-shot cleanup of orphan AI-side metadata from pre-fix demo
signups.

Lucas's 2026-05-05 review: before BE PR #389 we were calling
``discover_connection(space_id=visitor_space)`` per signup, leaving
N×20 ``table_metadata`` rows + matching ``embeddings`` for every
demo visitor. The shared-indexing fix prevents this going forward,
but the leftover rows still occupy bytes and skew per-space queries
that scan the full table.

This script deletes per-space metadata for the configured demo
connections **only**. Real-client connections (those whose UUID is
not in ``DEMO_DATASET_CONNECTION_IDS``) are untouched.

Idempotent — running twice is a no-op the second time. Safe to run
on a live DB; demo visitors with NULL-keyed shared rows keep working
(those rows have ``space_id IS NULL`` and are not touched).

Usage:
    python -m scripts.cleanup_orphan_demo_metadata          # dry-run
    python -m scripts.cleanup_orphan_demo_metadata --apply  # delete
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Make repo root importable when running as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.database import AsyncSessionLocal


def _demo_connection_ids() -> List[str]:
    raw = os.getenv("DEMO_DATASET_CONNECTION_IDS", "")
    return [c.strip() for c in raw.split(",") if c.strip()]


async def _count_orphans(db: AsyncSession, conn_ids: List[str]) -> dict:
    rows = (
        await db.execute(
            text(
                "SELECT (SELECT count(*) FROM table_metadata WHERE data_connection_id = ANY(:cids) AND space_id IS NOT NULL) AS table_metadata, "
                "(SELECT count(*) FROM embeddings WHERE table_metadata_id IN ("
                "  SELECT id FROM table_metadata WHERE data_connection_id = ANY(:cids) AND space_id IS NOT NULL"
                ")) AS embeddings"
            ),
            {"cids": conn_ids},
        )
    ).mappings().first()
    return {"table_metadata": int(rows["table_metadata"] or 0), "embeddings": int(rows["embeddings"] or 0)}


async def _delete_orphans(db: AsyncSession, conn_ids: List[str]) -> dict:
    # embeddings via JOIN before we drop the table_metadata rows.
    deleted_emb = (
        await db.execute(
            text(
                "DELETE FROM embeddings WHERE table_metadata_id IN ("
                "  SELECT id FROM table_metadata WHERE data_connection_id = ANY(:cids) AND space_id IS NOT NULL"
                ")"
            ),
            {"cids": conn_ids},
        )
    ).rowcount
    deleted_tm = (
        await db.execute(
            text(
                "DELETE FROM table_metadata WHERE data_connection_id = ANY(:cids) AND space_id IS NOT NULL"
            ),
            {"cids": conn_ids},
        )
    ).rowcount
    await db.commit()
    return {"table_metadata": int(deleted_tm), "embeddings": int(deleted_emb)}


async def main(apply_changes: bool) -> int:
    conn_ids = _demo_connection_ids()
    if not conn_ids:
        print("DEMO_DATASET_CONNECTION_IDS is empty — nothing to clean up.")
        return 0

    print(f"Scoping to {len(conn_ids)} demo connection(s):")
    for cid in conn_ids:
        print(f"  - {cid}")

    async with AsyncSessionLocal() as db:
        before = await _count_orphans(db, conn_ids)
        print(
            f"\nOrphan rows (space_id IS NOT NULL on demo connections):\n"
            f"  table_metadata: {before['table_metadata']}\n"
            f"  embeddings:     {before['embeddings']}"
        )

        if not apply_changes:
            print("\nDRY-RUN — no rows deleted. Re-run with --apply to delete.")
            return 0

        if before["table_metadata"] == 0 and before["embeddings"] == 0:
            print("\nNothing to delete.")
            return 0

        deleted = await _delete_orphans(db, conn_ids)
        print(
            f"\nDeleted:\n"
            f"  table_metadata: {deleted['table_metadata']}\n"
            f"  embeddings:     {deleted['embeddings']}"
        )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the orphan rows. Without this flag the script is dry-run.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(apply_changes=args.apply)))
