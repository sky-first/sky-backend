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
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base


_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")
_INET_OR_TEXT = INET().with_variant(String(length=45), "sqlite")
_TAGS_COL = ARRAY(String(length=64)).with_variant(JSON(), "sqlite")


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
    UPDATE_DB_CONFIG = "update_db_config"
    TEST_DB_CONFIG = "test_db_config"
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


# Canonical phase sequence for the GitHub Actions provisioning workflow.
# Kept in sync with the CHECK constraint on ``provisioning_job_events``
# (see migrations/versions/provisioning_events_20260530.py). The order
# of this tuple matters — ``provisioning_workflow.ingest_event`` uses it
# to decide whether a ``succeeded`` event should advance
# ``ProvisioningJob.current_phase`` to the next phase.
PROVISIONING_PHASES: tuple[str, ...] = (
    "preflight",
    "plan",
    "gitops",
    "namespaces",
    "secrets",
    "bootstrap",
    "smoke",
    "report",
)


class ProvisioningJobEventStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProvisioningJobEventLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


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
            "'update_capacity', 'update_db_config', 'test_db_config', "
            "'grant_role', 'revoke_role')",
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

    # Workflow engine (provisioning_events_20260530). ``current_phase``
    # is the last phase the workflow reported as ``succeeded`` and the
    # UI uses it to highlight the active step. The two ``external_*``
    # fields point back at the GitHub Actions run that owns this job.
    current_phase = Column(String(32), nullable=True)
    external_run_id = Column(String(64), nullable=True)
    external_run_url = Column(Text(), nullable=True)

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


class ProvisioningJobEvent(Base):
    """One row per phase transition reported by the GitHub Actions workflow.

    The workflow POSTs a signed webhook to ``/api/console/v1/jobs/webhook``
    at the start, success, and failure of every phase
    (``preflight`` → … → ``report``). Each call appends one row here. The
    Console UI subscribes to ``/api/console/v1/jobs/{id}/events`` (SSE)
    which replays this table then tails the Redis pub/sub channel
    ``provisioning_job_events:<job_id>``.

    The column ``event_metadata`` deliberately avoids the name
    ``metadata`` because SQLAlchemy reserves that on ``DeclarativeBase``.
    """

    __tablename__ = "provisioning_job_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    phase = Column(String(32), nullable=False)
    status = Column(String(20), nullable=False)
    level = Column(
        String(20), nullable=False, server_default="info", default="info"
    )
    message = Column(Text(), nullable=True)
    event_metadata = Column(
        _JSONB_OR_JSON, nullable=False, server_default=text("'{}'"), default=dict
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "phase IN ('preflight', 'plan', 'gitops', 'namespaces', "
            "'secrets', 'bootstrap', 'smoke', 'report')",
            name="provisioning_job_events_phase_check",
        ),
        CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')",
            name="provisioning_job_events_status_check",
        ),
        CheckConstraint(
            "level IN ('info', 'warning', 'error')",
            name="provisioning_job_events_level_check",
        ),
        Index(
            "idx_provisioning_job_events_job_created",
            "job_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<ProvisioningJobEvent job={self.job_id} phase={self.phase!r} "
            f"status={self.status!r} level={self.level!r}>"
        )


class ConsoleCSMNotes(Base):
    """Per-tenant CSM relationship state.

    Lives next to the platform's tenant_registry so the CSM tab can
    pull / save without crossing into the per-tenant DB. Slug is the
    PK and the join key; survives tenant soft-destroy so history
    isn't lost when a customer churns.
    """

    __tablename__ = "console_tenant_csm_notes"

    tenant_slug = Column(String(50), primary_key=True)
    notes_markdown = Column(Text(), nullable=True)
    tags = Column(_TAGS_COL, nullable=False, default=list, server_default=text("'{}'"))
    last_contact_at = Column(DateTime(timezone=True), nullable=True)
    nps_score = Column(Integer, nullable=True)
    next_renewal_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by = Column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "nps_score IS NULL OR (nps_score >= -100 AND nps_score <= 100)",
            name="console_csm_notes_nps_range",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<ConsoleCSMNotes tenant={self.tenant_slug!r} "
            f"tags={list(self.tags or [])}>"
        )


class ConsoleRole(str, Enum):
    """The 9 functional roles from docs/projeto-b-roles-and-use-cases.md.

    ``ceo`` and ``cto`` are the only roles that see everything; the
    rest are scoped. ``admin`` / ``operator`` / ``read_only`` from the
    old env-var system are mapped onto these as:
      old admin    -> ceo
      old operator -> tech_lead
      old read_only -> backend_eng (lowest read-only)
    """

    CEO = "ceo"
    CTO = "cto"
    TECH_LEAD = "tech_lead"
    DEVOPS = "devops"
    BACKEND_ENG = "backend_eng"
    AI_ENG = "ai_eng"
    CSM = "csm"
    SALES = "sales"
    FINANCE = "finance"
    SUPPORT = "support"
    DPO = "dpo"


class ConsoleRoleGrant(Base):
    """One row per active (email, role). A user can have many roles."""

    __tablename__ = "console_role_grants"

    user_email = Column(String(255), primary_key=True)
    role = Column(String(32), primary_key=True)
    granted_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    granted_by = Column(String(255), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by = Column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "role IN ('ceo', 'cto', 'tech_lead', 'devops', "
            "'backend_eng', 'ai_eng', 'csm', 'sales', 'finance', "
            "'support', 'dpo')",
            name="console_role_grants_role_check",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<ConsoleRoleGrant {self.user_email!r} → {self.role!r}"
            f"{' revoked' if self.revoked_at else ''}>"
        )


class ConsoleTenantCompliance(Base):
    """DPA + data residency + compliance flags per tenant (It6 — DPO)."""

    __tablename__ = "console_tenant_compliance"

    tenant_slug = Column(String(50), primary_key=True)
    dpa_status = Column(
        String(20), nullable=False, server_default="pending", default="pending"
    )
    dpa_signed_at = Column(DateTime(timezone=True), nullable=True)
    dpa_signed_by = Column(String(255), nullable=True)
    dpa_expires_at = Column(DateTime(timezone=True), nullable=True)
    data_residency = Column(
        String(32), nullable=False, server_default="eu-west-1", default="eu-west-1"
    )
    compliance_flags = Column(_JSONB_OR_JSON, nullable=False, default=dict)
    subprocessors_approved = Column(
        _TAGS_COL, nullable=False, default=list, server_default=text("'{}'")
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by = Column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "dpa_status IN ('pending', 'signed', 'expired', 'na')",
            name="console_compliance_dpa_status_check",
        ),
    )


class ConsoleSupportTicket(Base):
    """Customer-raised support tickets handled in the Console (It7)."""

    __tablename__ = "console_support_tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_slug = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text(), nullable=True)
    severity = Column(
        String(16), nullable=False, default="medium", server_default="medium"
    )
    status = Column(String(16), nullable=False, default="open", server_default="open")
    assigned_to = Column(String(255), nullable=True)
    reporter_email = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="console_support_severity_check",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting_customer', 'resolved', 'closed')",
            name="console_support_status_check",
        ),
        Index("idx_console_support_tenant_status", "tenant_slug", "status"),
    )


class ConsoleImpersonationSession(Base):
    """Audited Sky-team-member impersonation of a tenant user (It7)."""

    __tablename__ = "console_impersonation_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_email = Column(String(255), nullable=False)
    tenant_slug = Column(String(50), nullable=False)
    target_user_email = Column(String(255), nullable=False)
    reason = Column(Text(), nullable=False)
    ticket_id = Column(String(36), nullable=True)
    started_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at = Column(DateTime(timezone=True), nullable=True)
    customer_consent = Column(Boolean, nullable=False, default=False, server_default=text("false"))
