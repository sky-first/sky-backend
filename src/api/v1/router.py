"""Main API router."""

from fastapi import APIRouter, Depends

from src.api.deps import enforce_device_tenant
from src.api.v1 import _test as _test_endpoints
from src.api.v1 import (
    admin_actions,
    agents,
    ai,
    audit,
    auth,
    beats,
    branding,
    change_requests,
    chat_sessions,
    chat_ws,
    comments,
    connections,
    connectors,
    context_health,
    context_rows,
    context_semantic,
    conversations,
    cost_metrics,
    crews,
    cursor,
    data_access_requests,
    datasets,
    db_health,
    demo,
    devices,
    enterprise_apis,
    enterprise_relationships,
    files,
    glossary,
    impersonation,
    insight_agents,
    insights,
    insights_analytics,
    knowledge,
    messages,
    metrics,
    mfa,
    notifications,
    pages,
    permission_grants,
    permissions,
    presence,
    privacy,
    settings,
    settings_metrics,
    sharing,
    spaces,
    starred,
    support,
    templates,
    tenant_plan,
    tickets,
    users,
    voice,
    widgets,
)

api_router = APIRouter()

# Authentication endpoints
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Multi-Factor Authentication (Phase 3) — TOTP enrolment + management.
# The login-time MFA redemption (POST /auth/login/mfa) lives on the
# auth router so it can be called without a valid access token; this
# router covers the authenticated enrolment + status + disable flows.
api_router.include_router(mfa.router, prefix="/mfa", tags=["MFA"])

# Public demo signup — gated by DEMO_ENABLED. Mounted as a sibling to
# /auth so it lives outside any middleware that assumes the user is
# already authenticated.
api_router.include_router(demo.router, prefix="/demo", tags=["Demo"])
api_router.include_router(
    data_access_requests.router,
    prefix="/access-requests",
    tags=["Access requests"],
)

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

# Chat sessions — "Chat 1 / 2 / 3" containers per page. Collection under
# /pages, single-session ops under /chat-sessions.
api_router.include_router(chat_sessions.page_router, prefix="/pages", tags=["Chat Sessions"])
api_router.include_router(chat_sessions.router, prefix="/chat-sessions", tags=["Chat Sessions"])

# Message endpoints — nested under conversations for list/create/fork,
# top-level /messages for pin.
api_router.include_router(messages.conversation_router, prefix="/conversations", tags=["Messages"])
api_router.include_router(messages.router, prefix="/messages", tags=["Messages"])

# Insight-mode agent endpoints — mounted under /agents/insight so the
# pre-existing /agents (question/datasource/sql) CRUD stays untouched.
api_router.include_router(insight_agents.router, prefix="/agents/insight", tags=["Insight Agents"])

# Widget endpoints
# (Former /dashboards/* router removed 2026-05-20 — dashboard concept
# folded into Page; widget CRUD lives under /pages/{page_id}/widgets
# in pages.py and direct widget mutations under /widgets/{widget_id}.)
api_router.include_router(widgets.router, prefix="/widgets", tags=["Widgets"])

# Connection endpoints
api_router.include_router(connections.router, prefix="/connections", tags=["Connections"])

# Permission endpoints
api_router.include_router(permissions.router, prefix="/permissions", tags=["Permissions"])

# Per-user delegable permission grants (Knowledge refactor Phase 3 —
# starts with knowledge.certify, more delegations land later as the
# matrix expands). Mounted under /users/{id}/permission-grants.
api_router.include_router(permission_grants.router, prefix="/users", tags=["Permission Grants"])

# Generic per-resource sharing (Phase 2 of RBAC rewrite). Single endpoint
# family replaces the per-table grant tables (ConnectionPermission etc.)
# with rows in resource_acl. Resource type is in the path.
api_router.include_router(sharing.router, prefix="/resources", tags=["Resource Sharing"])

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
api_router.include_router(devices.router, prefix="/devices", tags=["Devices"])

# Space endpoints
api_router.include_router(spaces.router, prefix="/spaces", tags=["Spaces"])

# Crew endpoints
api_router.include_router(crews.router, prefix="/crews", tags=["Crews"])

# AI endpoints
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
# Voice session persistence (BE-07 slice)
api_router.include_router(voice.router, prefix="/voice", tags=["Voice"])
# BE-01 — the Insights feed is device-facing; enforce the signed tenant claim
# (no-op in single-tenant mode, pass-through for web sub-domain requests).
api_router.include_router(
    insights.router,
    prefix="/insights",
    tags=["Insights"],
    dependencies=[Depends(enforce_device_tenant)],
)

# Beats / quota usage. /me/beats returns the caller's own slice
# (everyone can read theirs); /tenant/beats aggregates across the
# org and is Owner/Admin-only via audit.view.
api_router.include_router(beats.router, prefix="", tags=["Beats"])

# Insights Analytics — Owner-only value-meter dashboard.
api_router.include_router(insights_analytics.router, prefix="", tags=["Insights Analytics"])

# Template endpoints
api_router.include_router(templates.router, prefix="/templates", tags=["Templates"])

# Settings endpoints
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])

# Tenant-wide branding (owner-only writes; reads open to any auth user).
api_router.include_router(branding.router, prefix="/branding", tags=["Branding"])

# Tenant plan tier (owner-only writes; reads open to any auth user).
# The topbar usage card reads it to decide which plan label / upgrade
# CTA to render.
api_router.include_router(tenant_plan.router, prefix="/tenant-plan", tags=["Tenant Plan"])

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
api_router.include_router(
    context_semantic.router, prefix="/context", tags=["Universe Intelligence v2"]
)

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

# /workspaces DESMONTADO em 16/08/2026.
#
# Onze endpoints servidos em produção que ninguém chamava. Verificado em
# todos os repositórios — frontend, app, sky-ai e os workers deste backend:
# zero referências. Numa API interna isso é decisivo, porque os únicos
# consumidores possíveis são os nossos próprios clientes.
#
# É vocabulário de uma versão anterior, do tempo em que "workspace" era o
# contentor. Hoje esse papel é do Projeto (a tabela ainda se chama `spaces`)
# e do Tenant. O `/spaces`, o `/crews` e o `/planets` do frontend contam a
# mesma história de nomes que se sobrepuseram sem ninguém limpar os
# anteriores.
#
# O que fica de PROPÓSITO: o modelo, as tabelas `workspaces` /
# `workspace_members`, o `workspace_service` e os seus testes. Desmontar uma
# rota é reversível numa linha; apagar tabelas não é, e não há pressa
# nenhuma para o fazer sem confirmar que estão vazias.
#
# Se algum dia isto fizer falta, é descomentar:
# api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])

# Starred items endpoints
api_router.include_router(starred.router, prefix="/starred", tags=["Starred"])

# Comment endpoints
api_router.include_router(comments.router, prefix="/comments", tags=["Comments"])

# Change-request endpoints — chat ↔ widget bridge (chat-threads-master-plan PR3).
api_router.include_router(
    change_requests.router, prefix="/change-requests", tags=["Change Requests"]
)
api_router.include_router(
    change_requests.widget_router, prefix="/widgets", tags=["Change Requests"]
)

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

# Cursor relay (WebSocket) endpoints
api_router.include_router(cursor.router, prefix="", tags=["Cursor"])

# Chat WebSocket relay — broadcasts message.created / conversation.pinned /
# conversation.resolved / change_request.created / change_request.resolved
# to every connected peer on a page (chat-threads-master-plan PR4).
api_router.include_router(chat_ws.router, prefix="", tags=["Chat WS"])

# Customer-raised support tickets — distinct from /support which manages
# Sky-operator JIT sessions.
api_router.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])

# Multi-tenant smoke endpoints (Projeto A). Public by design — they
# return only the resolver's view of the current request, never any
# customer data. Listed in auth.public_paths so they bypass JWT.
api_router.include_router(_test_endpoints.router, prefix="/_test", tags=["Multi-tenant smoke"])
