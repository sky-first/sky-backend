"""SQLAlchemy models."""

# IMPORTANT: every model must be imported here so that it registers itself with
# `Base.metadata`. The test fixture calls `Base.metadata.create_all` on an
# in-memory SQLite to provision the schema, and any model not in the registry
# at that point will be missing its table — causing `sqlite3.OperationalError:
# no such table: <name>` at runtime when the service layer queries it.
from src.models.agent import Agent, AgentExecution, AgentFinding
from src.models.audit import AuditEvent
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
from src.models.comment import Comment
from src.models.conversation import Conversation, Message
from src.models.connection import ColumnMetadata, ConnectionMetadata, DataConnection, TableMetadata
from src.models.crew import Crew, CrewMember
from src.models.dashboard import Connection, Dashboard, Widget
from src.models.dashboard_build_job import DashboardBuildJob
from src.models.enterprise_api import EnterpriseAPI
from src.models.enterprise_relationship import EnterpriseRelationship
from src.models.file import FileUpload
from src.models.glossary import GlossaryTerm
from src.models.intelligence_signal import IntelligenceSignal
from src.models.notification import Notification, NotificationPreference
from src.models.permission import APIKey, ConnectionPermission, Integration
from src.models.page import Page, PageMember
from src.models.signal_event import SignalEvent
from src.models.space import Space, SpaceConnection, SpaceMember, SpaceTable
from src.models.starred import StarredItem
from src.models.strategy import (
    StrategicObjective,
    StrategicPillar,
    StrategyAssumption,
    StrategyCycle,
    StrategyInitiative,
    StrategyKeyResult,
    StrategyOKR,
)
from src.models.template import Template
from src.models.ticket import Ticket, TicketEvent
from src.models.user import RefreshToken, User
from src.models.workspace import Workspace, WorkspaceMember

__all__ = [
    "Agent",
    "AgentFinding",
    "AgentExecution",
    "AuditEvent",
    "ContextDocument",
    "ContextDocumentKind",
    "ContextDocumentVisibility",
    "ServicePrincipal",
    "User",
    "RefreshToken",
    "Page",
    "PageMember",
    "StarredItem",
    "Dashboard",
    "Widget",
    "Connection",
    "DashboardBuildJob",
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
    "FileUpload",
    "GlossaryTerm",
    "Workspace",
    "WorkspaceMember",
    "Notification",
    "NotificationPreference",
    "Comment",
    "Conversation",
    "Message",
    "SignalEvent",
    "EnterpriseRelationship",
    "EnterpriseAPI",
    "IntelligenceSignal",
    "StrategicPillar",
    "StrategicObjective",
    "StrategyOKR",
    "StrategyInitiative",
    "StrategyAssumption",
    "StrategyCycle",
    "StrategyKeyResult",
]
