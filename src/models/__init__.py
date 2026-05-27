"""SQLAlchemy models."""

# IMPORTANT: every model must be imported here so that it registers itself with
# `Base.metadata`. The test fixture calls `Base.metadata.create_all` on an
# in-memory SQLite to provision the schema, and any model not in the registry
# at that point will be missing its table — causing `sqlite3.OperationalError:
# no such table: <name>` at runtime when the service layer queries it.
from src.models.agent import Agent, AgentExecution, AgentFinding
from src.models.audit import AuditEvent
from src.models.beat_consumption import BeatConsumption
from src.models.context_document import (
    ContextDocument,
    ContextDocumentKind,
    ContextDocumentVisibility,
)
from src.models.service_principal import ServicePrincipal
from src.models.ai import (
    AIFeedback,
    AIHistory,
    AIQuery,
    AIResponse,
    ChatMessage,
    Pipeline,
    PipelineStep,
)
from src.models.change_request import ChangeRequest
from src.models.comment import Comment
from src.models.conversation import Conversation, Message
from src.models.connection import ColumnMetadata, ConnectionMetadata, DataConnection, TableMetadata
from src.models.crew import Crew, CrewMember
from src.models.widget import Connection, Widget, WidgetFeedback
from src.models.page_build_job import PageBuildJob
from src.models.enterprise_api import EnterpriseAPI
from src.models.enterprise_relationship import EnterpriseRelationship
from src.models.file import FileUpload
from src.models.glossary import GlossaryTerm
from src.models.metric import Metric
from src.models.notification import Notification, NotificationPreference
from src.models.permission import APIKey, ConnectionPermission, Integration
from src.models.resource_acl import ResourceAcl
from src.models.platform_branding import PlatformBranding
from src.models.page import Page, PageMember
from src.models.space import Space, SpaceConnection, SpaceMember, SpaceTable
from src.models.starred import StarredItem
from src.models.tenant import DEFAULT_CAPACITY_SHAPE, Tenant, TenantTier
from src.models.internal_console import (
    AuditAction,
    AuditResult,
    ConsoleCSMNotes,
    InternalConsoleAudit,
    ProvisioningJob,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
# Strategy entities (Pillar/Objective/OKR/Initiative/KeyResult/Assumption/
# Cycle) were dropped in the Knowledge refactor Phase 1a (2026-04-25).
# Events/Signals (SignalEvent / IntelligenceSignal) were dropped in
# Phase 1b. Strategy semantics fold into Metric attributes (tags /
# target_value / threshold) in Phase 2; agent findings surface directly
# in the Pulse halo. See sky-security/docs/KNOWLEDGE_REFACTOR.md.
from src.models.template import Template
from src.models.ticket import Ticket, TicketEvent
from src.models.user import RefreshToken, User
from src.models.user_permission_grant import UserPermissionGrant
from src.models.workspace import Workspace, WorkspaceMember

__all__ = [
    "Agent",
    "AgentFinding",
    "AgentExecution",
    "AuditEvent",
    "BeatConsumption",
    "ContextDocument",
    "ContextDocumentKind",
    "ContextDocumentVisibility",
    "ServicePrincipal",
    "User",
    "RefreshToken",
    "Page",
    "PageMember",
    "StarredItem",
    "Widget",
    "WidgetFeedback",
    "Connection",
    "PageBuildJob",
    "DataConnection",
    "ConnectionMetadata",
    "TableMetadata",
    "ColumnMetadata",
    "Space",
    "SpaceMember",
    "SpaceConnection",
    "SpaceTable",
    "Crew",
    "CrewMember",
    "ConnectionPermission",
    "AIQuery",
    "AIHistory",
    "AIFeedback",
    "Pipeline",
    "PipelineStep",
    "ChatMessage",
    "AIResponse",
    "Template",
    "APIKey",
    "Integration",
    "PlatformBranding",
    "FileUpload",
    "GlossaryTerm",
    "Metric",
    "Workspace",
    "WorkspaceMember",
    "Notification",
    "NotificationPreference",
    "ChangeRequest",
    "Comment",
    "Conversation",
    "Message",
    "EnterpriseRelationship",
    "EnterpriseAPI",
    "UserPermissionGrant",
    "Tenant",
    "TenantTier",
    "DEFAULT_CAPACITY_SHAPE",
    "InternalConsoleAudit",
    "ProvisioningJob",
    "AuditAction",
    "AuditResult",
    "ProvisioningJobType",
    "ProvisioningJobStatus",
]
