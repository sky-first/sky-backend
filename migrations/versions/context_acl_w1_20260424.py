"""W1 — context_documents ACL hardening (chat/agent master plan §2).

Augments the existing ``context_documents`` table landed in
``add_context_documents_20260415.py`` with two security-critical columns:

1. ``content_hash`` (``TEXT``, NOT NULL) — SHA-256 of (kind, title, body,
   meta). Dedup key for the ingest worker (W2+). Indexed for fast lookup.
   Backfilled on upgrade using the same deterministic JSON canonicalization
   the ORM uses (``json.dumps(sort_keys=True, separators=(',',':'))``).

2. ``crew_ids`` (``UUID[]`` on Postgres, ``JSON`` on SQLite tests) —
   replaces the single ``crew_id`` for multi-crew ACL. Legacy ``crew_id``
   stays (backward compat, writes still populate both); retrieval path
   built in W2 queries ``crew_ids``. Backfill: for every row where
   ``crew_id IS NOT NULL``, set ``crew_ids = ARRAY[crew_id]``.

No drops, no destructive changes — safe to apply live.

Revision ID: context_acl_w1_20260424
Revises: agent_selected_context_20260423
Create Date: 2026-04-24
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "context_acl_w1_20260424"
down_revision = "agent_selected_context_20260423"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _sha256_hex(kind: str, title: str, body: str, meta) -> str:
    """Mirror ``ContextDocument.compute_content_hash``. Kept inline here so
    the migration stays self-contained and doesn't fail if the model file
    shape changes later."""
    if meta is None:
        meta = {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    payload = json.dumps(
        {"kind": kind, "title": title, "body": body, "meta": meta},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    pg = _is_postgres()

    # 1 — content_hash. Start nullable so existing rows can be backfilled
    # before we add NOT NULL.
    op.add_column(
        "context_documents",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )

    # 2 — crew_ids. Array on PG, JSON on SQLite (mirrors pii_flags pattern).
    if pg:
        op.add_column(
            "context_documents",
            sa.Column(
                "crew_ids",
                ARRAY(UUID(as_uuid=True)),
                nullable=False,
                server_default=sa.text("'{}'::uuid[]"),
            ),
        )
    else:
        op.add_column(
            "context_documents",
            sa.Column(
                "crew_ids",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )

    # 3 — backfill content_hash row by row (streaming).
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, kind, title, body, metadata_jsonb FROM context_documents"
        )
    ).fetchall()

    for row in rows:
        h = _sha256_hex(row[1] or "", row[2] or "", row[3] or "", row[4])
        bind.execute(
            sa.text(
                "UPDATE context_documents SET content_hash = :h WHERE id = :id"
            ),
            {"h": h, "id": row[0]},
        )

    # 4 — backfill crew_ids from legacy single crew_id (PG only — SQLite
    # tests start with empty tables).
    if pg:
        bind.execute(
            sa.text(
                "UPDATE context_documents "
                "SET crew_ids = ARRAY[crew_id] "
                "WHERE crew_id IS NOT NULL AND cardinality(crew_ids) = 0"
            )
        )

    # 5 — now we can enforce NOT NULL on content_hash.
    op.alter_column("context_documents", "content_hash", nullable=False)

    # 6 — index for dedup lookups (not unique; dedup is per-space in W2).
    op.create_index(
        "ix_context_documents_content_hash",
        "context_documents",
        ["content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_context_documents_content_hash", table_name="context_documents")
    op.drop_column("context_documents", "crew_ids")
    op.drop_column("context_documents", "content_hash")
