"""Main API router."""

from fastapi import APIRouter

from src.api.v1 import (
    ai,
    auth,
    comments,
    connections,
    connectors,
    crews,
    dashboards,
    datasets,
    files,
    notifications,
    permissions,
    planets,
    settings,
    spaces,
    starred,
    templates,
    users,
    widgets,
    workspaces,
    signal_events,
)

api_router = APIRouter()

# Authentication endpoints
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# User endpoints
api_router.include_router(users.router, prefix="/users", tags=["Users"])

# Planet endpoints
api_router.include_router(planets.router, prefix="/planets", tags=["Planets"])

# Dashboard endpoints
api_router.include_router(dashboards.router, prefix="/dashboards", tags=["Dashboards"])

# Widget endpoints
api_router.include_router(widgets.router, prefix="/widgets", tags=["Widgets"])

# Connection endpoints
api_router.include_router(connections.router, prefix="/connections", tags=["Connections"])

# Permission endpoints
api_router.include_router(permissions.router, prefix="/permissions", tags=["Permissions"])

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

# File upload endpoints
api_router.include_router(files.router, prefix="/files", tags=["Files"])

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

# Signal Events endpoints
api_router.include_router(signal_events.router, prefix="/signal-events", tags=["Signal Events"])

# TODO: Add more routers here as we implement them step by step
# Following the BACKEND_IMPLEMENTATION_MASTER_PLAN.md
