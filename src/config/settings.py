"""Application settings using Pydantic Settings."""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=[
            ".env.local",
            ".env",
            "../deploy/.env",
        ],  # Tenta .env.local primeiro (dev local), depois .env, depois deploy/.env
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "AI SaaS Dashboard Backend"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True  # Temporarily enabled for debugging
    ENVIRONMENT: str = "development"
    ADMIN_ONBOARDING_VERSION: int = 1

    # API
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = Field(
        default=(
            "http://localhost:3000,http://localhost:3001,"
            "http://127.0.0.1:3000,http://127.0.0.1:3001,"
            # Expo web dev server (Sky Mobile app) — harmless localhost origins.
            "http://localhost:19006,http://127.0.0.1:19006,"
            "http://localhost:8081,http://127.0.0.1:8081"
        ),
        description="CORS allowed origins (comma-separated)",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list."""
        if not self.CORS_ORIGINS:
            return ["http://localhost:3000", "http://localhost:3001"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # Database - can be built from separate env vars or provided as full URL
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db",
        description="Database connection URL (can be built from POSTGRES_* env vars)",
    )

    # Separate PostgreSQL environment variables (for Docker Compose)
    POSTGRES_USER: str = Field(default="postgres", description="PostgreSQL username")
    POSTGRES_PASSWORD: str = Field(default="", description="PostgreSQL password")
    POSTGRES_HOST: str = Field(default="localhost", description="PostgreSQL host")
    POSTGRES_PORT: int = Field(default=5432, description="PostgreSQL port")
    POSTGRES_DB: str = Field(default="ai_saas_db", description="PostgreSQL database name")

    @model_validator(mode="after")
    def build_database_url(self):
        """Build DATABASE_URL from separate env vars if available, otherwise use provided URL."""
        import os
        from urllib.parse import quote_plus

        # Check if we have separate PostgreSQL environment variables (Docker Compose setup)
        # Priority: env vars > Field defaults
        postgres_user = os.getenv("POSTGRES_USER") or self.POSTGRES_USER
        postgres_password = os.getenv("POSTGRES_PASSWORD") or self.POSTGRES_PASSWORD
        postgres_host = os.getenv("POSTGRES_HOST") or self.POSTGRES_HOST
        postgres_port_env = os.getenv("POSTGRES_PORT")
        postgres_db = os.getenv("POSTGRES_DB") or self.POSTGRES_DB

        # If POSTGRES_PASSWORD is set as env var, always build URL from separate vars
        if os.getenv("POSTGRES_PASSWORD"):
            encoded_password = quote_plus(postgres_password) if postgres_password else ""
            port_str = (
                f":{postgres_port_env}"
                if postgres_port_env
                else (f":{self.POSTGRES_PORT}" if self.POSTGRES_PORT != 5432 else "")
            )
            self.DATABASE_URL = f"postgresql+asyncpg://{postgres_user}:{encoded_password}@{postgres_host}{port_str}/{postgres_db}"

        # Helper to ensure async driver
        if self.DATABASE_URL and self.DATABASE_URL.startswith("postgresql://"):
            self.DATABASE_URL = self.DATABASE_URL.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )

        if self.DATABASE_URL and "@" in self.DATABASE_URL and "asyncpg" in self.DATABASE_URL:
            # Fix existing DATABASE_URL if password contains special characters
            import re

            # Format: postgresql+asyncpg://user:password@host:port/db
            pattern = r"^(postgresql(?:\+asyncpg)?)://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(.+)$"
            match = re.match(pattern, self.DATABASE_URL)

            if match:
                scheme, username, password, host, port, database = match.groups()

                # Check if password needs encoding
                from urllib.parse import unquote_plus

                try:
                    # Try to decode if it's already encoded
                    decoded_password = unquote_plus(password) if "%" in password else password
                    # Only re-encode if password contains special chars that need encoding
                    if (
                        any(
                            c in decoded_password
                            for c in ["/", "=", "+", "@", ":", "?", "#", "[", "]"]
                        )
                        or "%" not in password
                    ):
                        encoded_password = quote_plus(decoded_password)
                        port_part = f":{port}" if port else ""
                        self.DATABASE_URL = (
                            f"{scheme}://{username}:{encoded_password}@{host}{port_part}/{database}"
                        )
                except Exception:
                    # If any error in complex parsing, leave as is
                    pass

        return self

    # Per-process Postgres pool. The defaults were 20+10 = 30 per
    # process — combined with uvicorn --reload child processes +
    # Celery worker + AI ingest worker, that easily exceeds Postgres'
    # default max_connections=100 in dev and triggers \"FATAL: sorry,
    # too many clients already\". Down to 5+5 = 10/process leaves
    # ample headroom; production overrides via env when running on
    # a beefier Postgres instance.
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 5
    DATABASE_POOL_PRE_PING: bool = True

    # ─── Postgres pool hardening ──────────────────────────────────────────
    # How long a request waits for a free connection before failing fast.
    # Without it, a leak or saturation hangs the request indefinitely
    # while clients keep piling on; with a 30 s ceiling we surface the
    # incident at the request layer (5xx alerts fire) instead of
    # silently degrading throughput.
    DATABASE_POOL_TIMEOUT: int = 30

    # LIFO recycling — newest-released connection is the first one we
    # hand out. Keeps Postgres' query-planner caches warm and lets idle
    # connections drift to the recycle window naturally.
    DATABASE_POOL_USE_LIFO: bool = True

    # Per-connection statement timeout (Postgres ``statement_timeout``).
    # Keeps a single runaway query from holding the pool slot forever.
    # 30 s default — analytics queries should run via the AI worker, not
    # the API event loop.
    DATABASE_STATEMENT_TIMEOUT_MS: int = 30_000

    # Per-connection idle-in-transaction timeout. A leaked transaction
    # locks rows + occupies the connection; this kills the session
    # automatically after 60 s.
    DATABASE_IDLE_IN_TX_TIMEOUT_MS: int = 60_000

    # Lock-wait timeout. Failing fast is better than queuing requests
    # behind a long-running migration or DDL.
    DATABASE_LOCK_TIMEOUT_MS: int = 10_000

    # PgBouncer transaction-mode flag. asyncpg keeps a per-connection
    # prepared-statement cache by default; under PgBouncer transaction
    # pooling the same physical connection is shared by many clients,
    # so the cached statements collide. Setting this to ``True`` disables
    # the cache so PgBouncer can do its job.
    DATABASE_PGBOUNCER_MODE: bool = False

    # ─── Ticket escalation → Sky on-call ───────────────────────────────────
    # When a customer-side admin / owner escalates a ticket to "Sky team
    # review", we POST a JSON payload to this URL so the Sky on-call rotation
    # gets paged. Empty default = log-only mode (the structured WARN line in
    # ticket_service still fires for off-platform tooling that tails logs).
    TICKET_ESCALATION_WEBHOOK_URL: str = Field(
        default="",
        description=(
            "HTTPS URL that receives a JSON POST when a ticket is escalated. "
            "Empty disables the webhook and falls back to log-only escalation."
        ),
    )
    # Bearer token sent in the Authorization header on the webhook call.
    # Optional — leave empty if the receiver authenticates by IP allow-list.
    TICKET_ESCALATION_WEBHOOK_TOKEN: str = Field(default="")
    # Hard ceiling on the outbound POST so a slow Sky receiver can't stall
    # the escalate request. The escalate flow swallows the failure and
    # continues — the DB is the source of truth.
    TICKET_ESCALATION_WEBHOOK_TIMEOUT: float = 5.0

    # ─── Slack notification on ticket creation ────────────────────────────
    # Slack Incoming Webhook URL. When set, every newly-created ticket
    # fires an async best-effort POST to this URL with a Slack block-kit
    # payload (subject, severity, reporter, link). Empty = log-only.
    SLACK_TICKETS_WEBHOOK_URL: str = Field(
        default="",
        description=(
            "Slack Incoming Webhook URL that receives a Slack-formatted "
            "POST when a ticket is created. Empty disables the webhook."
        ),
    )
    SLACK_TICKETS_WEBHOOK_TIMEOUT: float = 5.0

    # Slack feedback channel — separate webhook for tickets with
    # category in {feature_request, other}. Bug tickets continue to
    # land in SLACK_TICKETS_WEBHOOK_URL. Lucas's brief: "1 canal para
    # tickets/bugs/escalations, 1 canal para features+feedbacks, 1
    # canal para demo signups." Empty = falls back to the tickets
    # webhook (preserves single-channel behaviour for installs that
    # haven't split yet).
    SLACK_FEEDBACK_WEBHOOK_URL: str = Field(
        default="",
        description=(
            "Slack Incoming Webhook URL for feature_request + other "
            "(non-bug) tickets. Empty falls back to SLACK_TICKETS_WEBHOOK_URL."
        ),
    )

    # Public app URL used to render a clickable link back to the ticket
    # in the Slack message. Falls back to skipping the link if empty.
    APP_PUBLIC_URL: str = Field(default="")

    # ─── Slack lead-gen webhook on demo signup ───────────────────────────
    # Separate webhook (different channel) from the tickets one. Empty
    # = log-only mode. Posts on every demo provisioning event:
    # cold signup, same-domain join, returning visitor.
    SLACK_DEMO_SIGNUPS_WEBHOOK_URL: str = Field(
        default="",
        description=(
            "Slack Incoming Webhook URL for demo-signup lead-gen events. "
            "Separate from SLACK_TICKETS_WEBHOOK_URL so support and "
            "marketing can use different channels."
        ),
    )
    SLACK_DEMO_SIGNUPS_WEBHOOK_TIMEOUT: float = 5.0

    # ─── Resend transactional email (demo welcome, ticket replies) ───────
    # Resend is the chosen vendor for launch — see
    # docs/strategy/EMAIL_PROVIDER_DECISION.md. Empty key = log-only
    # mode (no outbound HTTP, no real email sent). Same dry-run pattern
    # we use for TURNSTILE_SECRET_KEY.
    RESEND_API_KEY: str = Field(
        default="",
        description=(
            "Resend API key. Empty = log-only mode (dev/CI). Set in "
            "Azure KV as `resend-api-key` and reference via "
            "ExternalSecret in staging."
        ),
    )
    RESEND_API_URL: str = Field(default="https://api.resend.com/emails")
    RESEND_TIMEOUT: float = 10.0
    # O remetente tem de estar num domínio **verificado na Resend**, e o
    # que está verificado é o subdomínio `updates.` (DKIM em
    # `resend._domainkey.updates`, na zona do Route53). O domínio raiz
    # não está: enviar de `@skyfirstlabs.com` devolvia 403
    # `domain is not verified` — e como o serviço engole os erros por
    # design, isso lia-se como "o email deixou de funcionar".
    EMAIL_FROM_ADDRESS: str = Field(default="lucas.ventura@updates.skyfirstlabs.com")
    EMAIL_FROM_NAME: str = Field(default="Lucas Ventura — SKY")
    # Mas as respostas têm de cair na caixa real.
    #
    # O `updates.` só tem envio (`receiving: disabled` na Resend), por
    # isso sem isto uma resposta ao email de boas-vindas ia para um sítio
    # onde ninguém a lê — e o email inteiro existe para pedir resposta.
    EMAIL_REPLY_TO_ADDRESS: str = Field(default="lucas.ventura@skyfirstlabs.com")
    EMAIL_DASHBOARD_URL: str = Field(default="https://demo.skyfirstlabs.com")
    # Para onde vai o aviso de um contacto novo na demo pública.
    # Sem isto o lead ficava só na base de dados, e ninguém dava por
    # ele até alguém se lembrar de ir lá ver — que é o mesmo que não
    # ter formulário nenhum.
    DEMO_LEAD_NOTIFY_TO: str = Field(default="lucas.ventura@skyfirstlabs.com")

    # Redis
    REDIS_URL: str = Field(
        default="",
        description="Redis connection URL (empty to skip Redis - OK for local development)",
    )
    REDIS_HOST: Optional[str] = Field(
        default=None,
        description="Redis host (empty to use REDIS_URL or fallback to localhost in dev)",
    )
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    @model_validator(mode="after")
    def build_redis_url(self):
        """Build REDIS_URL from separate env vars if available and URL is empty."""
        import os

        # Priority: env var > Field default
        redis_host = os.getenv("REDIS_HOST") or self.REDIS_HOST
        redis_port = os.getenv("REDIS_PORT") or str(self.REDIS_PORT)
        redis_db = os.getenv("REDIS_DB") or str(self.REDIS_DB)
        redis_password = os.getenv("REDIS_PASSWORD") or self.REDIS_PASSWORD

        # Build REDIS_URL only if it's empty and we have at least a host
        if not self.REDIS_URL and redis_host:
            auth = f":{redis_password}@" if redis_password else ""
            self.REDIS_URL = f"redis://{auth}{redis_host}:{redis_port}/{redis_db}"
        elif not self.REDIS_URL and not redis_host and self.ENVIRONMENT != "development":
            # Safety check for non-development environments
            import logging

            logging.getLogger(__name__).warning(
                "REDIS_URL and REDIS_HOST are both empty in non-development environment"
            )

        return self

    # Celery
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/1",
        description="Celery broker URL",
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/2",
        description="Celery result backend URL",
    )

    # JWT
    JWT_SECRET_KEY: str = Field(
        description="JWT secret key — must be set via environment variable",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # BE-05 (Sky Mobile) — device clients keep a much longer refresh so users
    # aren't forced to re-auth on a phone every week; reuse-detection + family
    # revocation (see auth_service) is what keeps a long-lived token safe.
    JWT_REFRESH_TOKEN_EXPIRE_DAYS_MOBILE: int = 45

    # Password
    PASSWORD_HASH_ALGORITHM: str = "bcrypt"
    BCRYPT_ROUNDS: int = 12

    # Multi-Factor Authentication (Phase 3 — TOTP).
    # ``CONSOLE_REQUIRE_MFA`` gates Console access on the Sky-team
    # operator having MFA enabled. False by default so the rollout
    # can happen gradually — once every operator has enrolled, flip
    # this to true per-environment. When true and the operator has
    # mfa_enabled=false, ``require_sky_team`` returns 403 with the
    # body ``{"error": "mfa_required", "enroll_url": "/api/v1/mfa/enroll/start"}``
    # so the FE can route them to the enrolment modal.
    CONSOLE_REQUIRE_MFA: bool = False

    # App Store / Play review access. A comma-separated allowlist of emails
    # that sign in with email + password only (no MFA prompt) so a store
    # reviewer can enter — a TOTP challenge would block the review. Empty by
    # default (no exemption); set only in review/staging to a demo account on
    # demo data. NEVER add a real customer account here.
    MFA_EXEMPT_EMAILS: str = ""

    # Console host isolation. The Internal Console must only serve on
    # its own subdomain so a customer landing on the main app host
    # cannot reach the operator surface even with a forged JWT. The
    # ``require_sky_team`` dependency rejects 404 (not 403, to hide the
    # surface entirely) when the request host is outside this set.
    # Empty falls back to the safe defaults baked into
    # ``_allowed_console_hosts()``.
    CONSOLE_ALLOWED_HOSTS: str = ""

    # ─── Tenant create defaults (Lucas decision 2026-05-31) ──────────────
    # The Create Tenant form used to require the operator to type the
    # shared-RDS / shared-Redis hosts and the would-be Secrets Manager
    # ARNs by hand. The ``onboard-client.yml`` workflow already knows
    # how to derive those from the slug — so when the form leaves them
    # empty, the create handler fills them in from these defaults.
    # Operators can still override per-tenant via the Advanced section
    # if they ever need a dedicated DB instance for a customer.
    #
    # The ARN patterns include ``{slug}`` as a literal placeholder; the
    # handler does the substitution. Empty (the safe default) preserves
    # the legacy behaviour — required fields stay required.
    DEFAULT_TENANT_DB_HOST: str = ""
    DEFAULT_TENANT_DB_PORT: int = 5432
    DEFAULT_TENANT_DB_NAME_PATTERN: str = "tenant_{slug_safe}"
    DEFAULT_TENANT_DB_SECRET_ARN_PATTERN: str = ""
    DEFAULT_TENANT_REDIS_HOST: str = ""
    DEFAULT_TENANT_REDIS_SECRET_ARN: str = ""
    DEFAULT_TENANT_SSO_PROVIDER: str = "google"

    # Encryption (for connection credentials)
    ENCRYPTION_KEY: str = Field(
        default="your-32-byte-encryption-key-change-in-production",
        description="Encryption key for sensitive data (must be 32 bytes)",
    )

    # Multi-tenant platform (Projeto A — Model B). Default OFF: while
    # the flag is off, the tenant resolver middleware (PR #2+) falls back
    # to the platform's single-tenant defaults and the registry table
    # exists but is not consulted on the request path. Turn this on per
    # environment only after the full Phase 5 cutover.
    MULTI_TENANT_ENABLED: bool = False

    # Space→Crew model (2026-06): when ON, questions and agents may only be
    # asked/created against a CREW, never a bare Space. A collaborative
    # query (space_id present, is_personal=False) without a crew_id is
    # rejected at the API. This is a SECURITY boundary, not just a FE
    # nicety.
    #
    # OFF by default — this hard server-side enforcement must be rolled out
    # in lock-step with the crew-forcing frontend, so it is enabled
    # deliberately per environment (env var) only AFTER the FE that always
    # sends a crew_id is deployed. With it off, the FE still resolves the
    # space's default "General" crew at send time, so collaborative queries
    # remain crew-scoped in practice; flipping this on just adds the
    # belt-and-braces server-side rejection. Keeping the default off also
    # preserves backward-compatible behaviour for existing space-scoped
    # agents/queries (and the test suite).
    CREW_REQUIRED_FOR_QUERY: bool = False

    # Local-dev URL template used by ``TenantConnectionManager``. When
    # set, a single docker-compose Postgres can host many tenant DBs:
    # set this to e.g.
    #   ``postgresql+asyncpg://postgres:postgres@localhost:5432/{db_name}``
    # and create one Postgres DB per tenant.
    # Empty string => the manager falls back to ``ctx.db_credentials_secret_arn``
    # (production / AWS) and then to the platform's POSTGRES_* env vars
    # using the registry row's ``db_host`` / ``db_name``.
    TENANT_DB_URL_TEMPLATE: str = ""

    # Hard-fail when business logic reaches the DB without a real
    # tenant context (Projeto A PR #14). Off by default — flip to True
    # only after every customer-facing route has been verified to
    # populate the tenant context. Until then, ``tenant_guard`` logs
    # ``tenant_scope_violation`` warnings instead.
    STRICT_TENANT_REQUIRED: bool = False

    # Public demo (Cenário B) — visitor lands on demo.skyfirstlabs.com,
    # fills a short form, gets a per-visitor Space provisioned with a TTL.
    # All values overridable via env so staging/prod can clamp differently.
    DEMO_ENABLED: bool = False
    DEMO_TTL_DAYS: int = 7
    DEMO_RATE_LIMIT_PER_IP_PER_HOUR: int = 3
    DEMO_MAX_AGENTS_PER_USER: int = (
        10  # demo seeds 9 agents → 1 free slot so visitors can create one
    )
    DEMO_DATASET_CONNECTION_ID: str = ""  # legacy single Connection UUID
    DEMO_DATASET_CONNECTION_IDS: str = ""  # CSV of Connection UUIDs (preferred — multi-schema demo)
    TURNSTILE_SECRET_KEY: str = ""  # Cloudflare Turnstile (free)
    TURNSTILE_VERIFY_URL: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

    # Sentry
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"

    # Storage
    STORAGE_TYPE: str = "local"  # local, s3, gcs
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "us-east-1"
    GCS_BUCKET_NAME: str = ""
    GCS_PROJECT_ID: str = ""

    # Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@example.com"
    SMTP_USE_TLS: bool = True

    # AI Service
    AI_SERVICE_TYPE: str = Field(
        default="mock", description="AI service type: mock, real"
    )  # mock, real
    AI_SERVICE_URL: str = Field(
        default="http://localhost:8001",
        description="URL of the AI service (ia-do-projeto)",
    )
    AI_SERVICE_HTTP_TIMEOUT: float = Field(
        default=90.0,
        description=(
            "Seconds the backend will wait on a single AI HTTP call before "
            "aborting. Must be <= the frontend withTimeout (120s). Previous "
            "default of 25s caused spurious 'Service highly demanded' banners "
            "on any medium-complexity question."
        ),
    )
    AI_METADATA_TTL_SECONDS: int = Field(
        default=21600,
        description="TTL (seconds) for AI table metadata before re-discover is triggered. 0 disables staleness checks.",
    )
    AI_RESPONSE_CACHE_TTL_SECONDS: int = Field(
        default=600,
        description="TTL (seconds) for cached AI responses. 0 disables caching.",
    )

    # Cache warming (background scheduler)
    CACHE_WARMING_ENABLED: bool = Field(
        default=True,
        description="Enable periodic cache warming for AI response cache.",
    )
    CACHE_WARMING_INTERVAL_SECONDS: int = Field(
        default=300,
        description="Interval (seconds) for cache warming scheduler.",
    )
    CACHE_WARMING_LOOKBACK_HOURS: int = Field(
        default=24,
        description="Lookback window (hours) when selecting warm candidates.",
    )
    CACHE_WARMING_TOP_N_PER_CONNECTION: int = Field(
        default=10,
        description="Top N questions per connection to consider for warming.",
    )
    CACHE_WARMING_MAX_WARMS_PER_RUN: int = Field(
        default=50,
        description="Hard cap on how many cache entries to warm per scheduler run.",
    )
    CACHE_WARMING_MAX_SCAN_ROWS: int = Field(
        default=5000,
        description="Max recent AIQuery rows scanned per run (bounds DB work).",
    )
    CACHE_WARMING_MAX_TOTAL_CANDIDATES: int = Field(
        default=200,
        description="Max candidates kept after grouping/ranking (bounds CPU work).",
    )
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4"
    ANTHROPIC_API_KEY: str = ""

    # Knowledge Library — Azure Storage
    AZURE_STORAGE_ACCOUNT_NAME: str = ""  # empty = use local fallback in dev
    AZURE_STORAGE_CONTAINER_RAW: str = "uploads-raw"
    AZURE_STORAGE_CONTAINER_PROCESSED: str = "uploads-processed"

    # Knowledge Library — file/quota limits
    FILE_MAX_SIZE_MB: int = 15
    QUOTA_PERSONAL_FILES: int = 15
    QUOTA_PERSONAL_MB: int = 100
    QUOTA_CREW_FILES: int = 50
    QUOTA_CREW_MB: int = 500
    QUOTA_SPACE_FILES: int = 100
    QUOTA_SPACE_MB: int = 1024

    # Knowledge Library — processing
    EMBEDDING_BATCH_SIZE: int = 100
    FILE_PROCESSING_TIMEOUT_SECONDS: int = 300

    # Used by blob_helper local dev URLs
    BACKEND_BASE_URL: str = "http://localhost:8000"

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 300
    RATE_LIMIT_PER_HOUR: int = 10000

    # Console rate-limit bucket (Gap #2 from the 2026-05-30 security
    # posture audit). The Console is a low-volume operator surface with
    # destructive actions; budgeting it separately keeps a runaway
    # tenant burst from burning Console quota and a Console script gone
    # wild from draining the customer-facing budget.
    CONSOLE_RATE_LIMIT_PER_MINUTE: int = 60
    CONSOLE_RATE_LIMIT_PER_HOUR: int = 1000

    # ─── Console K8s telemetry (issue #39 / feat/console-telemetry-k8s-real) ──
    # When True, the InfraProvider factory returns the live Kubernetes-backed
    # provider (``KubernetesTelemetryProvider``) instead of the legacy mock or
    # the kubeconfig-based ``KubernetesInfraProvider``. The new provider uses
    # ``load_incluster_config()`` first (IRSA on EKS) and falls back to
    # ``load_kube_config()`` for local development. Off by default so PRs that
    # touch the Console do not require a live cluster in CI.
    #
    # NOTE: the K8s provider also requires CONSOLE_MOCK_INFRA=false to take
    # effect — when the mock flag is on it always wins, so dev/CI is safe.
    K8S_TELEMETRY_ENABLED: bool = False
    # Optional namespace allow-list for ``platform_health``. Empty = scan
    # all namespaces (requires cluster-wide list-pods RBAC). Comma-separated
    # values, e.g. ``"staging,production"``.
    K8S_TELEMETRY_NAMESPACES: str = ""
    # In-memory cache TTL for K8s API responses, in seconds. Prevents the
    # Console UI poll loop from rebooting the kube-apiserver. 30s matches the
    # frontend's auto-refresh cadence.
    K8S_TELEMETRY_CACHE_TTL_SECONDS: int = 30
    # Namespace name template. The provider derives a tenant's namespace
    # from its slug + the environment label. Two placeholders are supported:
    # ``{slug}`` and ``{env}`` (env ∈ {stg, prd}). Default mirrors the infra
    # convention ``<slug>-stg-aws`` / ``<slug>-prd-aws``.
    K8S_TELEMETRY_NAMESPACE_TEMPLATE: str = "{slug}-{env}-aws"

    # ─── Console AWS Cost Explorer telemetry (issue #40) ──────────────────────
    # When True, the CostProvider factory returns the live AWS Cost Explorer
    # provider (``AwsCostProvider``) instead of the mock. Off by default so
    # PRs that touch the Console do not require real AWS credentials in CI
    # (Cost Explorer API is paid: $0.01 per request).
    #
    # NOTE: the AWS provider also requires CONSOLE_MOCK_INFRA=false to take
    # effect — when the mock flag is on it always wins, so dev/CI is safe.
    AWS_COSTS_TELEMETRY_ENABLED: bool = False
    # Optional linked-account filter for cost queries. When empty, the
    # provider queries the master / payer account (sum across all linked
    # sub-accounts). Set to a 12-digit account id to scope queries to one
    # linked account (typical for tenant-isolated AWS sub-accounts).
    AWS_COSTS_LINKED_ACCOUNT_ID: Optional[str] = None
    # AWS region for the Cost Explorer endpoint. Cost Explorer is a global
    # service but boto3 still requires a region — eu-west-1 matches the
    # rest of SkyFirst's infra footprint.
    AWS_COSTS_REGION: str = "eu-west-1"

    # EUR→USD rate used to compare MRR (billed in EUR via Moloni) against
    # AWS spend (reported in USD by Cost Explorer) when computing gross
    # margin on the Console. Kept as a setting rather than a hardcoded
    # literal so it can be nudged without a code change; a live FX feed
    # can replace this later without touching the route.
    EUR_USD_RATE: float = 1.08

    # ─── Langfuse — LLM observability + cost tracking ─────────────────────
    # Langfuse is already wired in sky-poc-ai (see
    # ``core/agents/full_context_agent.py``) — every LLM call emits a
    # trace tagged with ``user_id`` / ``space_id`` / ``agent_id``. The
    # Console-side cost metrics endpoints in this repo read those
    # traces back via the Langfuse API so we get real cost per tenant /
    # per agent / per question without instrumenting every code path
    # ourselves.
    #
    # When ``LLM_METRICS_ENABLED=false`` the metrics service returns
    # empty payloads and the Console UI degrades to a "metrics off"
    # state — this is the safe default so a missing key or self-hosted
    # Langfuse outage doesn't break /api/console/v1/* endpoints.
    LANGFUSE_HOST: str = Field(
        default="https://cloud.langfuse.com",
        description=(
            "Langfuse base URL. Self-hosted deployments override to "
            "their internal endpoint (e.g. https://langfuse.skyfirstlabs.com). "
            "Empty disables both the SDK callback (in sky-poc-ai) and "
            "the metrics provider (this repo)."
        ),
    )
    LANGFUSE_PUBLIC_KEY: str = Field(
        default="",
        description=(
            "Langfuse project public key (pk-lf-…). Required by the "
            "API and the SDK callback. Empty = metrics disabled."
        ),
    )
    LANGFUSE_SECRET_KEY: str = Field(
        default="",
        description=(
            "Langfuse project secret key (sk-lf-…). Required by the "
            "API. Empty = metrics disabled. Stored in AWS Secrets "
            "Manager / Azure KV under `langfuse-secret-key`."
        ),
    )
    LLM_METRICS_ENABLED: bool = Field(
        default=False,
        description=(
            "Gate for the LLM cost metrics provider + Console "
            "endpoints. Off by default — flip to True only after "
            "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are wired in "
            "the environment. When False, the provider short-circuits "
            "to empty payloads (no outbound HTTP)."
        ),
    )
    LLM_METRICS_CACHE_TTL_SECONDS: int = Field(
        default=300,
        description=(
            "In-memory TTL for tenant / platform metric responses. "
            "Langfuse Cloud rate-limits the API at ~100 req/min per "
            "project; the Console UI polls every ~30s so a 5 minute "
            "TTL keeps us well below ceiling even with several "
            "concurrent operators."
        ),
    )
    LLM_METRICS_EUR_PER_USD: float = Field(
        default=0.92,
        description=(
            "Static FX rate used to convert the Langfuse USD figures "
            "into the EUR shown on the CEO dashboard. Matches the "
            "0.92 rate already hard-coded in services/ceo_dashboard.py "
            "until we wire a live FX feed."
        ),
    )

    # Tenant/User rate limiting for AI cost control (Subtask 2/3)
    AI_RATE_LIMIT_ENABLED: bool = True
    AI_RATE_LIMIT_USER_PER_MINUTE: int = 10
    AI_RATE_LIMIT_USER_PER_HOUR: int = 50
    AI_RATE_LIMIT_TENANT_PER_MINUTE: int = 40
    AI_RATE_LIMIT_TENANT_PER_HOUR: int = 200
    # Hard cap to prevent "switching tenant context" abuse
    AI_RATE_LIMIT_GLOBAL_USER_PER_HOUR: int = 80

    IDEMPOTENCY_TTL_SECONDS: int = Field(
        default=86400,
        description="TTL in seconds for idempotency keys stored in Redis.",
    )

    @model_validator(mode="after")
    def apply_environment_defaults(self):
        """
        Apply safer defaults for large-app development without impacting production.

        - In production: default to 300/min and 10000/hour unless explicitly set via env vars.
        - In development: keep rate limit enabled, but raise limits to avoid dev/HMR/test storms (3000/min).
        """
        import os

        is_prod = self.ENVIRONMENT == "production"

        # Only apply defaults when the env var is not explicitly set.
        if os.getenv("RATE_LIMIT_PER_MINUTE") is None:
            self.RATE_LIMIT_PER_MINUTE = 300 if is_prod else 3000
        if os.getenv("RATE_LIMIT_PER_HOUR") is None:
            self.RATE_LIMIT_PER_HOUR = 10000 if is_prod else 1000000
        if os.getenv("RATE_LIMIT_ENABLED") is None:
            # Keep enabled by default; can be disabled explicitly in env.
            self.RATE_LIMIT_ENABLED = True

        return self

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json, text

    # Prometheus
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090

    # Console telemetry: real-provider feature flags
    PROMETHEUS_ACTIVITY_ENABLED: bool = False
    PROMETHEUS_URL: str | None = None
    MOLONI_BILLING_ENABLED: bool = False
    MOLONI_API_KEY: str | None = None
    MOLONI_COMPANY_ID: str | None = None
    MOLONI_BASE_URL: str = "https://api.moloni.pt/v1"

    TENANT_BASE_DOMAINS: str = Field(
        default="skyfirstlabs.com",
        description=(
            "Domínios sob os quais um sub-domínio simples identifica um "
            "cliente (``gbt.skyfirstlabs.com`` → cliente ``gbt``). Lista "
            "separada por vírgulas. Fora destes, só um ``custom_domain`` "
            "declarado no registo é aceite — caso contrário bastava apontar "
            "um domínio qualquer ao nosso ingress para escolher o cliente."
        ),
    )

    def tenant_base_domains(self) -> List[str]:
        """A lista acima, limpa. Vazia = nenhum sub-domínio simples resolve."""
        return [
            d.strip().lower().lstrip(".")
            for d in (self.TENANT_BASE_DOMAINS or "").split(",")
            if d.strip()
        ]

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.ENVIRONMENT == "development"

    @property
    def database_url_sync(self) -> str:
        """Get synchronous database URL for Alembic."""
        from urllib.parse import urlparse, urlunparse

        # Parse the async URL
        parsed = urlparse(self.DATABASE_URL)

        # Remove +asyncpg from scheme
        scheme = parsed.scheme.replace("+asyncpg", "")

        # Password is already encoded in DATABASE_URL, so we can use it directly
        # psycopg2 will handle URL decoding automatically
        if parsed.password:
            # Keep the encoded password as-is (psycopg2 handles URL decoding)
            netloc = f"{parsed.username}:{parsed.password}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"

            return urlunparse(
                (
                    scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )

        # If no password, just remove +asyncpg
        return self.DATABASE_URL.replace("+asyncpg", "")


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
