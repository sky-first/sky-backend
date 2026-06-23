"""Rename sky_role ``ceo`` → ``owner``.

``ceo`` is a job title, not a permission. The Console role ladder
should describe *what someone can do on the platform*, not who they
are. ``owner`` (the highest authority over Sky-internal operations,
including provisioning, billing and offboarding tenants) matches the
industry-standard B2B SaaS hierarchy and parallels the tenant-side
PlatformRole ``owner`` ladder.

The rename also avoids the surprise of seeing a job title rendered as
a security level in the sidebar — a single individual can have any
title; the platform should not pretend otherwise.

Revision ID: sky_role_owner_20260529
Revises: sky_role_20260529
Create Date: 2026-05-29

The revision identifier was deliberately shortened to ``sky_role_owner_20260529``
(23 chars) — the cluster's ``alembic_version_be.version_num`` column is
``character varying(32)``, and the original
``sky_role_rename_ceo_to_owner_20260529`` (38 chars) blew up the migrate Job
with ``StringDataRightTruncation`` mid-upgrade. Lucas surfaced this when the
post-#459 deploy still couldn't promote the alembic head past the rename.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "sky_role_owner_20260529"
# down_revision originally pointed at ``provisioning_events_20260529``,
# which lives on an unmerged feature branch. Alembic couldn't resolve
# the chain on staging and silently refused to apply this migration —
# Lucas surfaced the bug when /me kept returning ``sky_role: "ceo"``
# after the rename was supposedly shipped. Pointing back at
# ``sky_role_20260529`` (the actual staging head when this migration
# landed) makes the chain solvable and lets alembic finally apply
# the UPDATE on the next pod start.
down_revision = "sky_role_20260529"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "sky_role" not in cols:
        return
    op.execute(sa.text("UPDATE users SET sky_role = 'owner' WHERE sky_role = 'ceo'"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "sky_role" not in cols:
        return
    op.execute(sa.text("UPDATE users SET sky_role = 'ceo' WHERE sky_role = 'owner'"))
