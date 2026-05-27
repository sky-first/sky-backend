"""Internal Console models — audit log + provisioning jobs (Projeto B).

These tables back the Sky-team admin Console (`/console` in sky-fe).
They live in the platform DB next to ``tenant_registry``; nothing about
them is per-tenant scoped because the Console operates across every
tenant.

Why a separate file rather than reusing the per-domain models: the
Console is owned by Sky engineering, not by any tenant, and the audit
log in particular is append-only with no foreign keys back to ``users``
(actors are identified by email since they live in the Sky team's
Google Workspace, not in any tenant DB).
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base


_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")
_INET_OR_TEXT = INET().with_variant(String(length=45), "sqlite")


class AuditAction(str, Enum):
    """Allowed values for ``InternalConsoleAudit.action``.

    Kept in sync with the CHECK constraint in the migration. New
    values require BOTH a migration that ALTERs the constraint AND a
    new entry here.
    """

    # reads
    VIEW_TENANT = "view_tenant"
    VIEW_AUDIT = "view_audit"
    VIEW_DASHBOARD = "view_dashboard"
    # writes — lifecycle
    CREATE_TENANT = "create_tenant"
    UPDATE_TENANT = "update_tenant"
    SUSPEND_TENANT = "suspend_tenant"
    RESUME_TENANT = "resume_tenant"
    DESTROY_TENANT = "destroy_tenant"
    CHANGE_TIER = "change_tier"
    UPDATE_CAPACITY = "update_capacity"
    # writes — auth / RBAC
    GRANT_ROLE = "grant_role"
    REVOKE_ROLE = "revoke_role"


class AuditResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class ProvisioningJobType(str, Enum):
    CREATE = "create"
    SUSPEND = "suspend"
    RESUME = "resume"
    DESTROY = "destroy"
    TIER_CHANGE = "tier_change"


class ProvisioningJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InternalConsoleAudit(Base):
    """Append-only audit log for every Console action.

    The table has no UPDATE or DELETE permissions in production (granted
    via separate Postgres role); the ORM is allowed to INSERT only. Do
    not add a relationship from a tenant model — the audit log
    survives tenant destruction by design.
    """

    __tablename__ = "internal_console_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_email = Column(String(255), nullable=False)
    actor_ip = Column(_INET_OR_TEXT, nullable=True)
    action = Column(String(100), nullable=False)
    tenant_slug = Column(String(50), nullable=True)
    request_payload = Column(_JSONB_OR_JSON, nullable=True)
    result = Column(String(20), nullable=False)
    result_details = Column(_JSONB_OR_JSON, nullable=True)
    timestamp = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('view_tenant', 'view_audit', 'view_dashboard', "
            "'create_tenant', 'update_tenant', 'suspend_tenant', "
            "'resume_tenant', 'destroy_tenant', 'change_tier', "
            "'update_capacity', 'grant_role', 'revoke_role')",
            name="internal_console_audit_action_check",
        ),
        CheckConstraint(
            "result IN ('success', 'failure', 'partial')",
            name="internal_console_audit_result_check",
        ),
        Index("idx_console_audit_tenant", "tenant_slug", "timestamp"),
        Index("idx_console_audit_actor", "actor_email", "timestamp"),
        Index("idx_console_audit_action", "action", "timestamp"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<InternalConsoleAudit actor={self.actor_email!r} "
            f"action={self.action!r} tenant={self.tenant_slug!r} "
            f"result={self.result!r}>"
        )


class ProvisioningJob(Base):
    """Long-running provisioning job spawned by the Console.

    Tracks the lifecycle of ``new-client.sh`` / ``manage-client.sh``
    invocations so the UI can poll for status and stream the script
    output. ``output`` collects stdout+stderr verbatim; the Console
    renders it in a terminal-style panel.
    """

    __tablename__ = "provisioning_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_slug = Column(String(50), nullable=False)
    actor_email = Column(String(255), nullable=False)
    job_type = Column(String(50), nullable=False)
    status = Column(
        String(20), nullable=False, server_default="pending", default="pending"
    )
    started_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    output = Column(Text(), nullable=True)
    error_message = Column(Text(), nullable=True)
    request_payload = Column(_JSONB_OR_JSON, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "job_type IN ('create', 'suspend', 'resume', 'destroy', 'tier_change')",
            name="provisioning_jobs_type_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', 'cancelled')",
            name="provisioning_jobs_status_check",
        ),
        Index("idx_provisioning_tenant", "tenant_slug", "started_at"),
        Index("idx_provisioning_status", "status", "started_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<ProvisioningJob id={self.id} type={self.job_type!r} "
            f"tenant={self.tenant_slug!r} status={self.status!r}>"
        )
