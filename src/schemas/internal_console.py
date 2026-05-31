"""Pydantic schemas for the Internal Console API (Projeto B).

Wire format for the ``/api/console/v1/*`` routes. Three groups:

* Audit log — read-only; the Console never POSTs to this surface
  directly. Audit entries are written by the service layer.
* Provisioning jobs — read-only from the client's perspective. POSTing
  to ``/tenants`` or ``/tenants/{slug}/suspend`` creates a job
  implicitly; the client polls the job by id.
* Tenant management — the Console-facing variants of the tenant
  schemas. Reuses :mod:`src.schemas.tenant` for the registry payload
  shape but wraps it with Console-specific extras (subscription dates,
  recent activity, computed capacity utilisation).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.internal_console import (
    AuditAction,
    AuditResult,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.schemas.tenant import TenantCreate, TenantRead, TenantUpdate


# ── Audit log ──────────────────────────────────────────────────────


class AuditEntryRead(BaseModel):
    """Single row from ``internal_console_audit``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_email: str
    actor_ip: Optional[str]
    action: AuditAction
    tenant_slug: Optional[str]
    request_payload: Optional[Dict[str, Any]]
    result: AuditResult
    result_details: Optional[Dict[str, Any]]
    timestamp: datetime

    @field_validator("actor_ip", mode="before")
    @classmethod
    def _coerce_ip(cls, v: Any) -> Optional[str]:
        # SQLAlchemy's INET type hands us an ``ipaddress.IPv4Address``
        # / ``IPv6Address`` rather than a string. Coerce here so the
        # Pydantic shape stays a plain str on the wire.
        if v is None:
            return None
        return str(v)


class AuditListResponse(BaseModel):
    items: List[AuditEntryRead]
    total: int


# ── Provisioning jobs ──────────────────────────────────────────────


class ProvisioningJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_slug: str
    actor_email: str
    job_type: ProvisioningJobType
    status: ProvisioningJobStatus
    started_at: datetime
    completed_at: Optional[datetime]
    output: Optional[str]
    error_message: Optional[str]
    request_payload: Optional[Dict[str, Any]]


class ProvisioningJobListResponse(BaseModel):
    items: List[ProvisioningJobRead]
    total: int


# ── Tenant management (Console wrappers) ───────────────────────────


class ConsoleTenantSummary(BaseModel):
    """Row shape for the Console's tenants-list table.

    Computed fields (``capacity_pct_*``) come from the service layer
    by combining ``tenant_registry.capacity_used`` with
    ``capacity_limits``. The frontend renders progress bars without
    re-computing.
    """

    model_config = ConfigDict(from_attributes=True)

    slug: str
    display_name: str
    tier: str
    is_active: bool
    suspended_at: Optional[datetime]
    custom_domain: Optional[str]
    created_at: datetime
    # ── computed by the service layer ──
    capacity_pct_agents: float = 0.0
    capacity_pct_sources: float = 0.0
    capacity_pct_indexed_gb: float = 0.0


class ConsoleTenantList(BaseModel):
    items: List[ConsoleTenantSummary]
    total: int


class ConsoleTenantDetail(TenantRead):
    """Tenant detail screen payload. Extends the registry shape with
    operational extras the Console renders on the Overview tab."""

    # Last 50 audit entries scoped to this tenant. Filled by the
    # service layer; the API never asks the client to provide it.
    recent_audit: List[AuditEntryRead] = Field(default_factory=list)
    # Last 10 provisioning jobs against this tenant.
    recent_jobs: List[ProvisioningJobRead] = Field(default_factory=list)


# ── Action payloads ────────────────────────────────────────────────


class CreateTenantRequest(TenantCreate):
    """Console-facing create payload.

    Adds an ``admin_email`` so the create handler can seed a real
    admin user in the freshly-provisioned tenant DB. Optional — if
    omitted the tenant is created with no admin and someone has to
    bootstrap one manually later.

    Data-plane fields (db_host, db_name, db_credentials_secret_arn,
    redis_host, redis_credentials_secret_arn, sso_provider) inherited
    from TenantCreate are overridden as Optional here. The Console
    handler derives them from settings + slug when the operator leaves
    them empty — see ``apply_data_plane_defaults`` for the rules.
    Operators can still type the values explicitly if they need a
    dedicated DB instance for a customer.
    """

    admin_email: Optional[str] = Field(
        None,
        description=(
            "If set, the create job also seeds a first admin user in "
            "the tenant DB with this email."
        ),
        max_length=255,
    )

    # ── Data-plane fields, now optional ──────────────────────────────
    # Pydantic v2: re-declaring an inherited field switches its
    # required-ness. Defaults are None so the validator below can tell
    # ``omitted`` apart from ``deliberately empty``.
    db_host: Optional[str] = Field(None, max_length=255)
    db_name: Optional[str] = Field(None, max_length=63)
    db_credentials_secret_arn: Optional[str] = Field(None, max_length=512)
    redis_host: Optional[str] = Field(None, max_length=255)
    redis_credentials_secret_arn: Optional[str] = Field(None, max_length=512)
    sso_provider: Optional[str] = Field(None, max_length=50)

    @model_validator(mode="after")
    def _apply_data_plane_defaults(self) -> "CreateTenantRequest":
        """Fill any data-plane field the operator left empty.

        Rules (driven by settings.DEFAULT_TENANT_*):

        - ``db_host``                  → settings.DEFAULT_TENANT_DB_HOST
        - ``db_name``                  → DEFAULT_TENANT_DB_NAME_PATTERN.format(slug_safe=…)
        - ``db_credentials_secret_arn``→ DEFAULT_TENANT_DB_SECRET_ARN_PATTERN.format(slug=…)
        - ``redis_host``               → settings.DEFAULT_TENANT_REDIS_HOST
        - ``redis_credentials_secret_arn`` → settings.DEFAULT_TENANT_REDIS_SECRET_ARN
        - ``sso_provider``             → settings.DEFAULT_TENANT_SSO_PROVIDER (or "google")

        ``slug_safe`` replaces dashes with underscores so the resulting
        DB name is a valid Postgres identifier. If a default is empty
        AND the operator did not provide a value, we raise the same
        error the legacy required-field would have — so a half-configured
        environment still fails loud at the API boundary instead of
        silently writing nulls to the tenant_registry row.
        """
        # Local import — settings has side-effects (singleton) that we
        # don't want loaded at module import time on the test path.
        from src.config.settings import settings

        slug = self.slug
        slug_safe = slug.replace("-", "_")

        def _coalesce(
            current: Optional[str], default: str, field_name: str
        ) -> str:
            if current and current.strip():
                return current
            if default and default.strip():
                return default
            raise ValueError(
                f"{field_name} is required (no default configured in settings)"
            )

        self.db_host = _coalesce(
            self.db_host,
            settings.DEFAULT_TENANT_DB_HOST,
            "db_host",
        )
        if not self.db_name or not self.db_name.strip():
            pattern = (
                settings.DEFAULT_TENANT_DB_NAME_PATTERN or "tenant_{slug_safe}"
            )
            self.db_name = pattern.format(slug=slug, slug_safe=slug_safe)
        if not self.db_credentials_secret_arn or not self.db_credentials_secret_arn.strip():
            pattern = settings.DEFAULT_TENANT_DB_SECRET_ARN_PATTERN
            if not pattern or not pattern.strip():
                raise ValueError(
                    "db_credentials_secret_arn is required "
                    "(no DEFAULT_TENANT_DB_SECRET_ARN_PATTERN configured)"
                )
            self.db_credentials_secret_arn = pattern.format(
                slug=slug, slug_safe=slug_safe
            )
        self.redis_host = _coalesce(
            self.redis_host,
            settings.DEFAULT_TENANT_REDIS_HOST,
            "redis_host",
        )
        self.redis_credentials_secret_arn = _coalesce(
            self.redis_credentials_secret_arn,
            settings.DEFAULT_TENANT_REDIS_SECRET_ARN,
            "redis_credentials_secret_arn",
        )
        if not self.sso_provider or not self.sso_provider.strip():
            self.sso_provider = (
                settings.DEFAULT_TENANT_SSO_PROVIDER or "google"
            )
        return self


class UpdateTenantRequest(TenantUpdate):
    """Console-facing update payload — passes straight through to the
    underlying tenant schema. Wrapper exists so future Console-only
    fields (e.g. CSM notes) can land here without touching the
    registry schema."""

    pass


class SuspendTenantRequest(BaseModel):
    """Optional reason payload for the suspend action."""

    reason: Optional[str] = Field(None, max_length=500)


class DestroyTenantRequest(BaseModel):
    """Confirmation token + double-typed slug — destruction is
    irreversible so the API requires the caller to type the slug
    twice and acknowledge."""

    confirmation_slug: str = Field(..., max_length=50)
    confirmation_phrase: str = Field(
        ..., description="Must be exactly 'I understand this is irreversible'"
    )


# ── Dashboard ──────────────────────────────────────────────────────


class DashboardSummary(BaseModel):
    """Aggregate stats for ``/api/console/v1/dashboard``."""

    total_tenants: int
    active_tenants: int
    suspended_tenants: int
    tenants_by_tier: Dict[str, int]
    recent_audit: List[AuditEntryRead] = Field(default_factory=list)


# ── CEO Master Dashboard ───────────────────────────────────────────


class CeoTierRow(BaseModel):
    tier: str
    active_tenants: int
    annual_price_eur: Optional[int]
    contracted_mrr_eur: float


class CeoChurnSignal(BaseModel):
    tenant_slug: str
    display_name: str
    reason: str  # "suspended" / "downgrade_blocked" / "no_recent_activity"
    detail: str


class CeoProvisioningHealth(BaseModel):
    pending: int
    running: int
    succeeded_last_24h: int
    failed_last_24h: int


class CeoMasterSummaryResponse(BaseModel):
    """``GET /api/console/v1/ceo`` payload.

    Single read Lucas (and any future CEO/CFO) opens to see where the
    business stands: ARR / MRR / margin / churn signals / provisioning
    pipeline health, in one place. All EUR per year unless noted.
    """

    computed_at: datetime
    total_tenants: int
    active_tenants: int
    suspended_tenants: int
    contracted_arr_eur: float
    contracted_mrr_eur: float
    last_month_cost_eur: float
    gross_margin_pct: Optional[float]
    tiers: List[CeoTierRow] = Field(default_factory=list)
    churn_signals: List[CeoChurnSignal] = Field(default_factory=list)
    provisioning: CeoProvisioningHealth
    # ─── LLM cost (Langfuse) ─────────────────────────────────────
    # Best-effort 30-day total. ``None`` means Langfuse is offline
    # / disabled — the UI renders a "metrics off" state and the rest
    # of the dashboard still loads. Exposed as EUR to match the
    # other monetary fields on this payload.
    llm_cost_30d_eur: Optional[float] = None


# ── LLM cost metrics (Langfuse-backed) ─────────────────────────────


class LlmByModelRow(BaseModel):
    """One row of the per-model breakdown."""

    model: str
    input_tokens: int
    output_tokens: int
    requests: int
    cost_usd: float


class LlmMetricsResponse(BaseModel):
    """``GET /api/console/v1/(tenants/{slug}|platform)/llm-metrics`` payload.

    ``available=False`` means the upstream Langfuse call failed (network /
    auth / disabled). The UI must render a "metrics offline" pill and
    skip the numbers — they're zero by contract, not by truth.
    """

    tenant_id: Optional[str] = None
    window_days: int
    from_ts: datetime
    to_ts: datetime
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    total_cost_eur: float
    by_model: List[LlmByModelRow] = Field(default_factory=list)
    cache_hit_rate_pct: float
    avg_latency_ms: float
    available: bool
    unavailable_reason: Optional[str] = None


# ── Me ─────────────────────────────────────────────────────────────


class ConsoleMeResponse(BaseModel):
    """``GET /api/console/v1/me`` — what the Console knows about the
    currently-authenticated Sky-team member."""

    email: str
    role: str  # admin | operator | read_only
    is_sky_team: bool


# ── Rich telemetry payloads (B#7-9) ────────────────────────────────


class PlatformHealthResponse(BaseModel):
    api_uptime_pct: float
    api_latency_p95_ms: int
    api_error_rate_pct: float
    pods_running: int
    pods_pending: int
    pods_crashlooping: int
    db_connections_used: int
    db_connections_max: int
    last_incident: Optional[str]


class TimeseriesPointModel(BaseModel):
    t: str
    value: float
    label: Optional[str] = None


class DashboardActivityResponse(BaseModel):
    points: List[TimeseriesPointModel]
    tenants: List[str]


class CostBreakdownModel(BaseModel):
    period_start: str
    period_end: str
    compute_usd: float
    storage_usd: float
    network_usd: float
    bedrock_usd: float
    total_usd: float
    daily: List[TimeseriesPointModel]


class RevenueSummaryResponse(BaseModel):
    mrr_eur: float
    this_month_spend_usd: float
    gross_margin_pct: float
    projection_eom_usd: float


class AlertModel(BaseModel):
    severity: str
    title: str
    detail: str
    tenant_slug: Optional[str]
    fired_at: str
    suggested_action: str


class AlertsResponse(BaseModel):
    items: List[AlertModel]


class IncidentModel(BaseModel):
    id: str
    severity: str
    title: str
    started_at: str
    resolved_at: Optional[str]
    affected_tenants: List[str]


class IncidentsResponse(BaseModel):
    items: List[IncidentModel]


class PodInfoModel(BaseModel):
    name: str
    namespace: str
    component: str
    status: str
    restarts: int
    cpu_pct: float
    memory_pct: float
    age_hours: int
    image_sha: str


class TenantHealthResponse(BaseModel):
    pods: List[PodInfoModel]
    last_deploy_at: str
    last_deploy_sha: str
    argocd_url: str
    grafana_url: str


class TenantBillingResponse(BaseModel):
    tier: str
    subscription_start: str
    subscription_end: str
    monthly_amount_eur: float
    payment_status: str
    last_invoice_at: str
    next_invoice_at: str
    mrr_contribution_eur: float


class TenantActivityResponse(BaseModel):
    points_7d: List[TimeseriesPointModel]
    total_queries_7d: int
    total_agents_runs_7d: int


class ClusterNodeModel(BaseModel):
    name: str
    cluster: str
    role: str
    cpu_pct: float
    memory_pct: float
    pods_count: int
    status: str


class InfraResponse(BaseModel):
    nodes: List[ClusterNodeModel]
    platform_health: PlatformHealthResponse


# ── Tier presets (It3 — B#16) ──────────────────────────────────────


class TierPresetResponse(BaseModel):
    slug: str
    display_name: str
    headline_price_eur: Optional[int]
    setup_fee_eur: Optional[int]
    pricing_unit: str
    capacity_limits: Dict[str, int]
    rate_limit_rpm: int
    rate_limit_tpm: int
    universe_intelligence_mode: str
    ai_processing_profile: str
    monitored_entities_cap: Optional[int]
    concurrent_sessions_cap: Optional[int]
    target_audience: str
    onboarding_scope: str
    support_sla: str
    bedrock_dedicated_profile: bool
    inclusions: List[str]


class ChangeTierRequest(BaseModel):
    tier: str = Field(..., description="Target tier slug")
    apply_preset: bool = Field(
        default=True,
        description=(
            "When true, capacity_limits is replaced with the tier preset. "
            "When false, the tier label changes but capacity_limits "
            "is preserved verbatim (custom contract case)."
        ),
    )


class UpdateCapacityLimitsRequest(BaseModel):
    agents: int = Field(..., ge=0)
    sources: int = Field(..., ge=0)
    indexed_gb: int = Field(..., ge=0)


# ── Tenant DB / Redis connection config (Console, GBT deploy) ──────
#
# Operators on the Sky team use these schemas to point a tenant at the
# right per-tenant Postgres / Redis pair. Until this lives in the
# Console, the only way to fix a tenant's connection details is a
# direct SQL UPDATE against ``tenant_registry`` — risky and unaudited.

_DB_HOST_REGEX = (
    r"^("
    r"(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
    r"|"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*"
    r")$"
)

_SECRET_ARN_REGEX = r"^arn:aws:secretsmanager:[a-z0-9-]+:\d{12}:secret:.+$"


class TenantDbConfigUpdate(BaseModel):
    """Partial update for a tenant's data-plane connection details.

    Every field is optional — the operator may patch one column at a
    time. The handler refuses an empty payload to avoid a no-op
    audit entry.
    """

    db_host: Optional[str] = Field(
        None, max_length=255, pattern=_DB_HOST_REGEX,
        description="DNS hostname or IPv4 address of the tenant's Postgres.",
    )
    db_port: Optional[int] = Field(
        None, ge=1, le=65535,
        description="TCP port — defaults to 5432 when unset.",
    )
    db_name: Optional[str] = Field(
        None, max_length=63,
        description="Postgres database name.",
    )
    db_credentials_secret_arn: Optional[str] = Field(
        None, max_length=512, pattern=_SECRET_ARN_REGEX,
        description="AWS Secrets Manager ARN with {username, password}.",
    )
    redis_host: Optional[str] = Field(
        None, max_length=255, pattern=_DB_HOST_REGEX,
        description="DNS hostname or IPv4 address of the tenant's Redis.",
    )
    redis_credentials_secret_arn: Optional[str] = Field(
        None, max_length=512, pattern=_SECRET_ARN_REGEX,
        description="AWS Secrets Manager ARN with the Redis AUTH token.",
    )


class TenantDbConfigRead(BaseModel):
    """The 6 connection fields as currently stored on the registry row.

    Secret ARNs are not masked here — the operator who authenticated
    as a sky-team member is allowed to see them. The audit log
    persists only a 30-char prefix.
    """

    model_config = ConfigDict(from_attributes=True)

    db_host: str
    db_port: int
    db_name: str
    db_credentials_secret_arn: str
    redis_host: str
    redis_credentials_secret_arn: str


class TenantDbConfigTestResult(BaseModel):
    """Outcome of ``POST /tenants/{slug}/db-config/test``.

    ``ok=true`` → the resolver could open a session and run
    ``SELECT 1``. ``ok=false`` → connection refused / auth failure;
    ``error`` carries the human-readable reason. Nothing is persisted.
    """

    ok: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    target_host: Optional[str] = None
    target_db: Optional[str] = None


# ── CSM notes (It3 — B#17) ─────────────────────────────────────────


class CSMTagModel(BaseModel):
    """Free-form CSM tags. The model is just a string list; this
    wrapper exists so the OpenAPI doc and the form library can pin
    common values for autocomplete."""

    pass


_KNOWN_CSM_TAGS = (
    "at_risk",
    "expansion_candidate",
    "reference_customer",
    "renewal_soon",
    "champion",
    "support_heavy",
    "do_not_contact",
)


class CSMNotesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_slug: str
    notes_markdown: Optional[str]
    tags: List[str]
    last_contact_at: Optional[datetime]
    nps_score: Optional[int]
    health_score: int  # computed, 0-100
    health_breakdown: Dict[str, int]
    next_renewal_at: Optional[datetime]
    updated_at: Optional[datetime]
    updated_by: Optional[str]


class CSMNotesUpdate(BaseModel):
    notes_markdown: Optional[str] = Field(None, max_length=20_000)
    tags: Optional[List[str]] = None
    last_contact_at: Optional[datetime] = None
    nps_score: Optional[int] = Field(None, ge=-100, le=100)


# ── Renewals (It3 — B#18) ──────────────────────────────────────────


class RenewalEntry(BaseModel):
    tenant_slug: str
    display_name: str
    tier: str
    next_renewal_at: datetime
    days_until: int
    monthly_amount_eur: float
    status: str  # upcoming / overdue / renewed


class RenewalsResponse(BaseModel):
    items: List[RenewalEntry]
    total_pipeline_eur: float


# ── RBAC (It4) ─────────────────────────────────────────────────────


class RoleGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_email: str
    role: str
    granted_at: datetime
    granted_by: str


class RoleGrantsListResponse(BaseModel):
    items: List[RoleGrantRead]
    available_roles: List[str]
    permission_actions: List[str]


class CreateRoleGrantRequest(BaseModel):
    user_email: str = Field(..., max_length=255)
    role: str


class MyAccessResponse(BaseModel):
    """``/me/access`` — what the current user can do.

    Frontend uses ``actions`` to hide / show UI primitives. Backend
    still enforces — this is UX only.
    """

    email: str
    roles: List[str]
    actions: List[str]


# ── Compliance / DPO (It6) ─────────────────────────────────────────


class ComplianceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_slug: str
    dpa_status: str
    dpa_signed_at: Optional[datetime]
    dpa_signed_by: Optional[str]
    dpa_expires_at: Optional[datetime]
    data_residency: str
    compliance_flags: Dict[str, Any]
    subprocessors_approved: List[str]
    updated_at: Optional[datetime]
    updated_by: Optional[str]


class ComplianceUpdate(BaseModel):
    dpa_status: Optional[str] = Field(
        None, description="pending / signed / expired / na"
    )
    dpa_signed_at: Optional[datetime] = None
    dpa_signed_by: Optional[str] = Field(None, max_length=255)
    dpa_expires_at: Optional[datetime] = None
    data_residency: Optional[str] = Field(None, max_length=32)
    compliance_flags: Optional[Dict[str, Any]] = None
    subprocessors_approved: Optional[List[str]] = None


class ComplianceSummary(BaseModel):
    """``/compliance/summary`` — DPO dashboard counts."""

    total_tenants: int
    dpa_signed: int
    dpa_pending: int
    dpa_expired: int
    by_residency: Dict[str, int]
    items: List[ComplianceRead]


# ── Support (It7) ──────────────────────────────────────────────────


class SupportTicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_slug: str
    title: str
    description: Optional[str]
    severity: str
    status: str
    assigned_to: Optional[str]
    reporter_email: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]
    updated_at: datetime


class SupportTicketCreate(BaseModel):
    tenant_slug: str = Field(..., max_length=50)
    title: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=10_000)
    severity: str = Field("medium")
    reporter_email: Optional[str] = Field(None, max_length=255)


class SupportTicketUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=10_000)
    severity: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = Field(None, max_length=255)


class SupportTicketsList(BaseModel):
    items: List[SupportTicketRead]
    open_count: int
    in_progress_count: int


# ── Impersonation (It7) ────────────────────────────────────────────


class ImpersonationStartRequest(BaseModel):
    target_user_email: str = Field(..., max_length=255)
    reason: str = Field(..., max_length=1_000)
    ticket_id: Optional[str] = Field(None, max_length=36)
    customer_consent: bool = Field(
        False, description="Required true to actually start"
    )


class ImpersonationSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_email: str
    tenant_slug: str
    target_user_email: str
    reason: str
    ticket_id: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    customer_consent: bool
    # Gap #6 from the 2026-05-30 security posture audit. The Console
    # never had a hard TTL on impersonation sessions; they could appear
    # "active" indefinitely. ``expires_at`` is computed as
    # ``started_at + IMPERSONATION_TTL`` (1h by default) and ``status``
    # rolls it up so the UI doesn't have to do the date math itself.
    expires_at: Optional[datetime] = None
    status: str = "active"  # "active" | "expired" | "ended"


# ── Notifications + Board Pack + Comparison (It8) ──────────────────


class Notification(BaseModel):
    id: str
    category: str  # alert / ticket / job / renewal
    severity: str  # info / warning / critical
    title: str
    detail: Optional[str]
    tenant_slug: Optional[str]
    href: Optional[str]
    timestamp: datetime


class NotificationsResponse(BaseModel):
    items: List[Notification]
    unread_count: int


class BoardPackResponse(BaseModel):
    """All-in-one snapshot the CEO can export for a board meeting."""

    generated_at: datetime
    generated_by: str
    metrics: Dict[str, float]
    tenants_by_tier: Dict[str, int]
    customers_at_risk: List[Dict[str, Any]]
    renewals_next_90d: List[Dict[str, Any]]
    cost_breakdown: Dict[str, float]
    revenue_summary: Dict[str, float]
    incidents_recent: List[Dict[str, Any]]


class TenantCompareEntry(BaseModel):
    slug: str
    display_name: str
    tier: str
    is_active: bool
    capacity_used: Dict[str, int]
    capacity_limits: Dict[str, int]
    health_score: int
    health_breakdown: Dict[str, int]
    queries_7d: int
    monthly_eur: float


class TenantCompareResponse(BaseModel):
    items: List[TenantCompareEntry]
