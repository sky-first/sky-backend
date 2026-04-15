"""Notification models — events, preferences, and category catalog."""

import uuid
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


# ---------------------------------------------------------------------------
# Notification type catalog
# ---------------------------------------------------------------------------

class NotificationType(str, Enum):
    """Every event the platform can surface to a user."""

    # Legacy values kept for backward compat with existing rows / tests
    SYSTEM = "system"
    ALERT = "alert"
    INSIGHT = "insight"
    SHARE = "share"
    MENTION = "mention"
    ACCESS = "access"
    NEW_INSIGHT_AVAILABLE = "new_insight_available"
    DASHBOARD_EDITED_BY_OTHER = "dashboard_edited_by_other"
    COMMENT_MENTION = "comment_mention"
    DASHBOARD_UPDATED = "dashboard_updated"

    # --- Agents ---
    AGENT_FINDING = "agent_finding"
    AGENT_ERROR = "agent_error"
    AGENT_PAUSED = "agent_paused"
    AGENT_RESUMED = "agent_resumed"
    AGENT_CYCLE_NO_FINDINGS = "agent_cycle_no_findings"
    # Phase 3.3 — insight-mode specific. Split from AGENT_FINDING so
    # users can mute insight rerun noise (low signal-to-noise in busy
    # dashboards) without silencing agent findings they actually want.
    INSIGHT_AGENT_MATERIAL = "insight_agent_material"  # delta_kind='material'
    INSIGHT_AGENT_RESULT = "insight_agent_result"      # every completed run

    # --- Dashboards ---
    DASHBOARD_SHARED_WITH_YOU = "dashboard_shared_with_you"
    DASHBOARD_COMMENT_ADDED = "dashboard_comment_added"
    DASHBOARD_WIDGET_ADDED_BY_OTHER = "dashboard_widget_added_by_other"

    # --- Pages ---
    PAGE_MEMBER_ADDED = "page_member_added"
    PAGE_SHARED_WITH_YOU = "page_shared_with_you"

    # --- Collaboration ---
    SPACE_MEMBER_ADDED = "space_member_added"
    SPACE_MEMBER_REMOVED = "space_member_removed"
    CREW_MEMBER_ADDED = "crew_member_added"
    CREW_MEMBER_REMOVED = "crew_member_removed"
    ROLE_CHANGED = "role_changed"
    INVITE_RECEIVED = "invite_received"

    # --- Connections ---
    CONNECTION_SYNC_FAILED = "connection_sync_failed"
    CONNECTION_SYNC_RESTORED = "connection_sync_restored"
    CONNECTION_NEW_TABLE_DISCOVERED = "connection_new_table_discovered"

    # --- Events / Signals ---
    SIGNAL_EVENT_CREATED = "signal_event_created"
    HIGH_CONFIDENCE_SIGNAL = "high_confidence_signal"

    # --- Strategy ---
    OKR_UPDATED = "okr_updated"
    INITIATIVE_STATUS_CHANGED = "initiative_status_changed"
    KEY_RESULT_TARGET_REACHED = "key_result_target_reached"


# Category label for each type — drives frontend filter tabs and preference
# grouping. Keep the category strings short and stable (they are stored in
# the preference table's scope_value column).
NOTIFICATION_CATEGORY: dict[str, str] = {
    # Agents
    "agent_finding": "agents",
    "agent_error": "agents",
    "agent_paused": "agents",
    "agent_resumed": "agents",
    "agent_cycle_no_findings": "agents",
    "new_insight_available": "agents",
    "insight_agent_material": "agents",
    "insight_agent_result": "agents",

    # Dashboards
    "dashboard_shared_with_you": "dashboards",
    "dashboard_comment_added": "dashboards",
    "dashboard_widget_added_by_other": "dashboards",
    "dashboard_edited_by_other": "dashboards",
    "dashboard_updated": "dashboards",

    # Pages
    "page_member_added": "pages",
    "page_shared_with_you": "pages",

    # Mentions
    "comment_mention": "mentions",

    # Collaboration
    "space_member_added": "collaboration",
    "space_member_removed": "collaboration",
    "crew_member_added": "collaboration",
    "crew_member_removed": "collaboration",
    "role_changed": "collaboration",
    "invite_received": "collaboration",

    # Events / Signals
    "signal_event_created": "events",
    "high_confidence_signal": "events",

    # Connections
    "connection_sync_failed": "connections",
    "connection_sync_restored": "connections",
    "connection_new_table_discovered": "connections",

    # Strategy
    "okr_updated": "strategy",
    "initiative_status_changed": "strategy",
    "key_result_target_reached": "strategy",

    # System / legacy
    "system": "system",
    "alert": "system",
    "insight": "agents",
    "share": "collaboration",
    "mention": "mentions",
    "access": "collaboration",
}


# ---------------------------------------------------------------------------
# Notification model (events table — append-only)
# ---------------------------------------------------------------------------

class Notification(Base):
    """Notification model — one row per event per recipient."""

    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Notification details
    type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Linked entity (for deep-linking and context)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(255), nullable=False)
    deep_link = Column(String(500), nullable=True)

    # Status
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user = relationship("User", backref="notifications")

    __table_args__ = (Index("idx_notifications_user_unread", "user_id", "is_read"),)

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, user_id={self.user_id}, type={self.type}, title={self.title})>"


# ---------------------------------------------------------------------------
# Notification preference model (per-user mute / pause rules)
# ---------------------------------------------------------------------------

class NotificationPreference(Base):
    """User preference for muting/pausing notifications.

    Scope resolution order (first match wins):
        1. global  — pause everything (focus mode)
        2. category — mute an entire category like "agents" or "mentions"
        3. source  — mute a specific entity like "agent:<uuid>" or "dashboard:<uuid>"
    """

    __tablename__ = "notification_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # What this preference controls
    scope_type = Column(String(20), nullable=False)      # "global" | "category" | "source"
    scope_value = Column(String(255), nullable=True)      # null for global, "agents" for category, "agent:<uuid>" for source

    # Which delivery channel — "all" means every channel
    channel = Column(String(20), nullable=False, default="all")  # "in_app" | "email" | "push" | "all"

    # State
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user = relationship("User", backref="notification_preferences")

    __table_args__ = (
        UniqueConstraint("user_id", "scope_type", "scope_value", "channel", name="uq_notif_pref_user_scope_channel"),
        Index("idx_notif_pref_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<NotificationPreference(user={self.user_id}, scope={self.scope_type}:{self.scope_value}, enabled={self.enabled})>"
