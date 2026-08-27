"""Space schemas."""

from datetime import datetime
from typing import Literal, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.user import UserResponse


class SpaceBase(BaseModel):
    """Base space schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None)  # Allow any string or None, validate in service if needed
    icon: Optional[str] = None
    # **Todos os projetos são privados.**
    #
    # O campo existe na base e é guardado, mas NUNCA é lido: nenhuma decisão
    # de acesso o consulta — nem o `acesso_ao_projeto`, nem o RBAC. Quem
    # alcança um projeto alcança-o por convite (`space_members`) ou por uma
    # equipa vinculada (`space_crews`), e mais nada.
    #
    # «Público» era, por isso, uma promessa que o servidor não cumpria: quem
    # o escolhia ficava convencido de que tinha aberto o projeto à empresa.
    # O ecrã deixou de o oferecer (27/08); aqui deixa de ser aceite, para não
    # voltar por outra porta.
    #
    # Abrir um projeto a toda a empresa é uma decisão de produto por tomar —
    # e implica escrevê-la na resolução de acesso, não só num campo.
    privacy: Literal["private"] = "private"
    sensitivity: str = Field("internal", description="internal, confidential, restricted")

    @field_validator("color", mode="before")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        """Validate and normalize color value."""
        if v is None or v == "":
            return None
        # If it's already a valid hex color, return as is
        if isinstance(v, str) and v.startswith("#") and len(v) == 7:
            try:
                int(v[1:], 16)  # Validate hex
                return v
            except ValueError:
                pass
        # If it's a color name or invalid format, return None
        return None


class SpaceCreate(SpaceBase):
    """Space creation schema."""


class SpaceUpdate(BaseModel):
    """Space update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None)  # Allow any string or None, validate in service if needed
    icon: Optional[str] = None
    # Ver `SpaceBase.privacy`: só existe «private».
    privacy: Optional[Literal["private"]] = None
    sensitivity: Optional[str] = Field(None, pattern="^(internal|confidential|restricted)$")


class SpaceResponse(SpaceBase):
    """Space response schema."""

    id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    member_count: int = 0
    connection_count: int = 0

    model_config = ConfigDict(from_attributes=True)


# Space roles — deliberately NOT reusing platform role names. Using
# Phase 7 — Space-axis vocabulary is exclusively owner / editor / viewer.
# Writes outside this set 400 at the schema validator. The resolver also
# floors any unknown value back to viewer at runtime so DB drift fails
# closed.
SPACE_MEMBER_ROLES = {"owner", "editor", "viewer"}


class SpaceMemberCreate(BaseModel):
    """Space member creation schema."""

    user_id: UUID
    # Per-space role. Default mirrors the BE column default — every
    # invited member starts as an editor and is promoted explicitly.
    role: str = "editor"


class SpaceMemberUpdate(BaseModel):
    """Change an existing space member's role."""

    role: str


class SpaceMemberResponse(BaseModel):
    """Space member response schema."""

    id: UUID
    space_id: UUID
    user_id: UUID
    role: str = "editor"
    user: Optional[UserResponse] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpaceTableCreate(BaseModel):
    """Space table creation schema."""

    connection_id: UUID
    table_name: str
    schema_name: Optional[str] = None


class SpaceTableResponse(BaseModel):
    """Space table response schema."""

    id: UUID
    space_id: UUID
    connection_id: UUID
    table_name: str
    schema_name: Optional[str] = None
    # Per-space column visibility — columns the Space chose to hide on
    # this table. Empty list means every column is visible (default).
    # Populated by sky-poc-backend#190 and consumed by the Space detail
    # drawer to pre-select the right toggles.
    hidden_columns: list[str] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpaceMetric(BaseModel):
    """Schema for a metric in the space overview."""

    value: str
    change: str
    trend: str  # 'up', 'down', 'neutral'


class SpaceActivity(BaseModel):
    """Schema for an activity in the space feed."""

    id: str
    user: str
    action: str
    target: str
    time: str
    status: str  # "allow" | "deny"


class SpaceComplianceStatus(BaseModel):
    """Structured compliance indicator derived from space sensitivity level."""

    status: str        # "INTERNAL" | "CONFIDENTIAL" | "RESTRICTED"
    description: str


class SpaceStatsResponse(BaseModel):
    """Schema for a space's statistics."""

    total_queries: SpaceMetric
    active_users: SpaceMetric
    data_usage: SpaceMetric
    compliance_status: SpaceComplianceStatus
    activity_feed: List[SpaceActivity]

    model_config = ConfigDict(from_attributes=True)
