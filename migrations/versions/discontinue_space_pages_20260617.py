"""discontinue orphan space-level pages (crew-only model)

In the crew-centric model a user never sits on a bare Space — entering a Space
lands them in its default Crew, and collaboration happens on the crew's
canonical page. Space-level pages (space_id set, crew_id NULL) are therefore
unreachable orphans. Soft-delete them so they disappear from every listing.

Demo-owned pages are LEFT ALONE: the demo sandbox is exempt from the
force-crew flow and regenerates its own space page on entry — deleting them
would just churn. Soft-delete (deleted_at) keeps the data recoverable and
avoids touching dependent widgets/members (all filtered by page.deleted_at).

Idempotent: re-running only affects rows still live.

Revision ID: discontinue_space_pages_20260617
Revises: page_canonical_20260617
Create Date: 2026-06-17

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "discontinue_space_pages_20260617"
down_revision = "page_canonical_20260617"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pages" not in inspector.get_table_names():
        return

    # Soft-delete non-demo orphan space-level pages. The join to users lets us
    # spare demo-owned pages (the demo sandbox still uses space pages).
    op.execute(
        sa.text(
            """
            UPDATE pages p
            SET deleted_at = now()
            FROM users u
            WHERE p.owner_id = u.id
              AND p.space_id IS NOT NULL
              AND p.crew_id IS NULL
              AND p.deleted_at IS NULL
              AND COALESCE(u.is_demo, false) = false
            """
        )
    )


def downgrade() -> None:
    # No-op: we can't reliably tell which previously-live space pages were
    # soft-deleted by THIS migration vs. by a user. Leaving them soft-deleted
    # on downgrade is the safe choice (they remain recoverable by id).
    pass
