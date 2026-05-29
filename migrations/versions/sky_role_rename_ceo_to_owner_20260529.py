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

Revision ID: sky_role_rename_ceo_to_owner_20260529
Revises: provisioning_events_20260529
Create Date: 2026-05-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "sky_role_rename_ceo_to_owner_20260529"
down_revision = "provisioning_events_20260529"
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
