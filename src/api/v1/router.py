"""Main API router."""

from fastapi import APIRouter

from src.api.v1 import (
    admin_actions,
    agents,
    ai,
    audit,
    auth,
    branding,
    comments,
    connections,
    connectors,
    context_health,
    context_rows,
    conversations,
    cost_metrics,
    crews,
    dashboards,
    db_health,
    datasets,
    demo,
    enterprise_apis,
    enterprise_relationships,
    files,
    glossary,
    impersonation,
    insight_agents,
    knowledge,
    messages,
    metrics,
    notifications,
    pages,
    permission_grants,
    permissions,
    promotions,
    presence,
    privacy,
    settings,
    settings_metrics,
    spaces,
    starred,
    support,
    templates,
    tickets,
    users,
    widgets,
    workspaces,
)

api_router = APIRouter()

# Authentication endpoints
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Public demo signup — gated by DEMO_ENABLED. Mounted as a sibling to
# /auth so it lives outside any middleware that assumes the user is
# already authenticated.
api_router.include_router(demo.router, prefix="/demo", tags=["Demo"])

# User endpoints
api_router.include_router(users.router, prefix="/users", tags=["Users"])

# Impersonation — ADR-001 Fase 2. Mounted under /users so the routes become
#   POST /users/{user_id}/impersonate
#   POST /users/me/impersonate/exit
api_router.include_router(impersonation.router, prefix="/users", tags=["Impersonation"])

# Page endpoints
api_router.include_router(pages.router, prefix="/pages", tags=["Pages"])

# Conversation endpoints — collection under /pages, operations under /conversations
api_router.include_router(conversations.page_router, prefix="/pages", tags=["Conversations"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["Conversations"])

# Message endpoints — nested under conversations for list/create/fork,
# top-level /messages for pin.
api_router.include_router(messages.conversation_router, prefix="/conversations", tags=["Messages"])
api_router.include_router(messages.router, prefix="/messages", tags=["Messages"])

# Insight-mode agent endpoints — mounted under /agents/insight so the
# pre-existing /agents (question/datasource/sql) CRUD stays untouched.
api_router.include_router(insight_agents.router, prefix="/agents/insight", tags=["Insight Agents"])

# Dashboard endpoints
api_router.include_router(dashboards.router, prefix="/dashboards", tags=["Dashboards"])

# Widget endpoints
api_router.include_router(widgets.router, prefix="/widgets", tags=["Widgets"])

# Connection endpoints
api_router.include_router(connections.router, prefix="/connections", tags=["Connections"])

# Permission endpoints
api_router.include_router(permissions.router, prefix="/permissions", tags=["Permissions"])

# Per-user delegable permission grants (Knowledge refactor Phase 3 —
# starts with knowledge.certify, more delegations land later as the
# matrix expands). Mounted under /users/{id}/permission-grants.
api_router.include_router(
    permission_grants.router, prefix="/users", tags=["Permission Grants"]
)

# Audit endpoints — mounted at /audit-logs (resource-oriented naming).
# The older /audit mount is kept so existing callers (if any) keep working
# while we migrate off it.
api_router.include_router(audit.router, prefix="/audit-logs", tags=["Audit"])
api_router.include_router(audit.router, prefix="/audit", tags=["Audit"], include_in_schema=False)

# Privacy endpoints (GDPR DSAR)
api_router.include_router(privacy.router, prefix="/privacy", tags=["Privacy"])

# Sky Support JIT endpoints
api_router.include_router(support.router, prefix="/support", tags=["Support"])

# Notification endpoints
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])

# Space endpoints
api_router.include_router(spaces.router, prefix="/spaces", tags=["Spaces"])

# Crew endpoints
api_router.include_router(crews.router, prefix="/crews", tags=["Crews"])

# AI endpoints
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])

# Template endpoints
api_router.include_router(templates.router, prefix="/templates", tags=["Templates"])

# Settings endpoints
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])

# Tenant-wide branding (owner-only writes; reads open to any auth user).
api_router.include_router(branding.router, prefix="/branding", tags=["Branding"])

# Settings Metrics endpoints
api_router.include_router(
    settings_metrics.router, prefix="/settings/metrics", tags=["Settings Metrics"]
)

# Context Layer health — admin-only; feeds the Administration tab in Settings.
api_router.include_router(context_health.router, prefix="/context", tags=["Context Health"])

# Database pool health — admin-only ops endpoint surfacing pool counters
# + a SELECT 1 ping. Pairs with the Postgres pool hardening settings
# (statement_timeout, idle_in_tx, pool_timeout, pgbouncer mode).
api_router.include_router(db_health.router, prefix="/db-health", tags=["DB Health"])

# Context rows — generic row-hydration endpoint used by the AI service's
# ingest worker to fetch the full source row before embedding. Paired
# with the Redis event stream in src/core/context_events.py.
api_router.include_router(context_rows.router, prefix="/context", tags=["Context Rows"])

# Admin actions (pause-all, audit export) — admin-only.
api_router.include_router(admin_actions.router, prefix="/admin", tags=["Admin Actions"])

# Cost breakdown (per-crew + daily series) — extends Settings Usage.
api_router.include_router(
    cost_metrics.router, prefix="/settings/metrics", tags=["Settings Metrics"]
)

# File upload endpoints
api_router.include_router(files.router, prefix="/files", tags=["Files"])

# Knowledge Library endpoints
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge"])

# Dataset management endpoints
api_router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])

# Connector registry endpoints
api_router.include_router(connectors.router, prefix="/connectors", tags=["Connectors"])

# Workspace endpoints
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])

# Starred items endpoints
api_router.include_router(starred.router, prefix="/starred", tags=["Starred"])

# Comment endpoints
api_router.include_router(comments.router, prefix="/comments", tags=["Comments"])

# Signal Events / Intelligence Signals endpoints removed in the Knowledge
# refactor Phase 1b (2026-04-25). They were not part of the new Knowledge
# model (Sources + Knowledge + Relationships) — agent-emitted findings
# now surface directly in the Pulse halo and Universe Intelligence.
#
# Strategy endpoints removed in Phase 1a (2026-04-25). Pillar / OKR /
# Initiative / Risk / Goal / Cycle / Assumption / KeyResult fold into
# Metric attributes (tags, target_value, threshold). The replacement
# /knowledge endpoint family lands in Phase 2 of the refactor — see
# sky-security/docs/KNOWLEDGE_REFACTOR.md.

# Glossary endpoints — business vocabulary consumed by the context layer
api_router.include_router(glossary.router, prefix="/glossary", tags=["Glossary"])

# Metrics endpoints (Knowledge refactor Phase 2 — replaces Pillar/OKR/Risk
# entities with a unified Metric model carrying tags + target + threshold).
api_router.include_router(metrics.router, prefix="/metrics", tags=["Metrics"])

# Promotion flow (Phase 4) — Personal → Crew → Space → Org with
# dependency resolver + conflict detection.
api_router.include_router(
    promotions.metric_router, prefix="/metrics", tags=["Knowledge Promotion"]
)
api_router.include_router(
    promotions.request_router,
    prefix="/promotion-requests",
    tags=["Knowledge Promotion"],
)
api_router.include_router(
    promotions.conflict_router,
    prefix="/knowledge-conflicts",
    tags=["Knowledge Promotion"],
)

# Enterprise Relationship endpoints
api_router.include_router(
    enterprise_relationships.router,
    prefix="/enterprise/relationships",
    tags=["Enterprise Relationships"],
)

# Enterprise API endpoints
api_router.include_router(
    enterprise_apis.router,
    prefix="/enterprise/apis",
    tags=["Enterprise APIs"],
)

# Agent endpoints
api_router.include_router(agents.router, prefix="/agents", tags=["Agents"])

# Presence (WebSocket) endpoints
api_router.include_router(presence.router, prefix="", tags=["Presence"])

# Customer-raised support tickets — distinct from /support which manages
# Sky-operator JIT sessions.
api_router.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
