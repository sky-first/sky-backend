"""chat sessions — named chat containers per page + backfill

Adds the ``chat_sessions`` table and ``conversations.session_id`` so a page
can hold multiple chats ("Chat 1", "Chat 2", …), each with its own timeline,
while the canvas stays shared at the page level.

Backfill: every page that already has conversations gets one default
"Chat 1" session (inheriting the page's space/crew scope), and all existing
conversations on that page are assigned to it — so nothing lands session-less.

Revision ID: chat_sessions_20260609
Revises: tenant_logo_url_20260603
Create Date: 2026-06-09
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "chat_sessions_20260609"
down_revision = "tenant_logo_url_20260603"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. chat_sessions table.
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("page_id", sa.UUID(), nullable=False),
        sa.Column("space_id", sa.UUID(), nullable=True),
        sa.Column("crew_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_sessions_page_id", "chat_sessions", ["page_id"])
    op.create_index("ix_chat_sessions_space_id", "chat_sessions", ["space_id"])
    op.create_index("ix_chat_sessions_crew_id", "chat_sessions", ["crew_id"])
    op.create_index("ix_chat_sessions_created_by", "chat_sessions", ["created_by"])

    # 2. conversations.session_id (nullable FK, SET NULL on session delete).
    op.add_column(
        "conversations", sa.Column("session_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "conversations_session_id_fkey",
        "conversations",
        "chat_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_conversations_session_id", "conversations", ["session_id"]
    )

    # 3. Backfill — one default "Chat 1" per page that has conversations,
    #    inheriting the page's space/crew scope, then assign every existing
    #    conversation to it. gen_random_uuid() is built in on Postgres 14+.
    op.execute(
        """
        INSERT INTO chat_sessions
            (id, page_id, space_id, crew_id, title, position, created_by, created_at, updated_at)
        SELECT gen_random_uuid(), p.id, p.space_id, p.crew_id, 'Chat 1', 0, p.owner_id, now(), now()
        FROM pages p
        WHERE EXISTS (SELECT 1 FROM conversations c WHERE c.page_id = p.id)
        """
    )
    op.execute(
        """
        UPDATE conversations c
        SET session_id = s.id
        FROM chat_sessions s
        WHERE s.page_id = c.page_id AND c.session_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_session_id", table_name="conversations")
    op.drop_constraint(
        "conversations_session_id_fkey", "conversations", type_="foreignkey"
    )
    op.drop_column("conversations", "session_id")
    op.drop_index("ix_chat_sessions_created_by", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_crew_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_space_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_page_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
