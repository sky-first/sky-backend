from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategicPillarBase(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    horizon: Optional[str] = None
    owner: Optional[str] = None
    metrics: Optional[List[str]] = Field(default_factory=list)
    priority: Optional[str] = None
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None


class StrategicPillarCreate(StrategicPillarBase):
    pass


class StrategicPillarUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    horizon: Optional[str] = None
    owner: Optional[str] = None
    metrics: Optional[List[str]] = None
    priority: Optional[str] = None


class StrategicPillarResponse(StrategicPillarBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Strategic Objective ---


class StrategicObjectiveBase(BaseModel):
    pillar_id: Optional[UUID] = None
    type: str  # corporate, unit, team, team_leader
    title: str
    description: Optional[str] = None
    status: Optional[str] = "on_track"
    priority: Optional[str] = None
    area: Optional[str] = None
    owner: Optional[str] = None
    kpis: Optional[List[str]] = Field(default_factory=list)
    budget: Optional[float] = None
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None


class StrategicObjectiveCreate(StrategicObjectiveBase):
    pass


class StrategicObjectiveUpdate(BaseModel):
    pillar_id: Optional[UUID] = None
    type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    area: Optional[str] = None
    owner: Optional[str] = None
    kpis: Optional[List[str]] = None
    budget: Optional[float] = None
    owner_crew_id: Optional[UUID] = None


class StrategicObjectiveResponse(StrategicObjectiveBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Strategy OKR ---


class StrategyOKRBase(BaseModel):
    objective_id: UUID
    cycle_id: Optional[UUID] = None
    title: str
    linked_kpi_id: Optional[str] = None
    baseline: Optional[float] = None
    target: Optional[float] = None
    deadline: Optional[datetime] = None
    measurement_frequency: Optional[str] = None
    owner_crew_id: Optional[UUID] = None
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None


class StrategyOKRCreate(StrategyOKRBase):
    pass


class StrategyOKRUpdate(BaseModel):
    objective_id: Optional[UUID] = None
    cycle_id: Optional[UUID] = None
    title: Optional[str] = None
    linked_kpi_id: Optional[str] = None
    baseline: Optional[float] = None
    target: Optional[float] = None
    deadline: Optional[datetime] = None
    measurement_frequency: Optional[str] = None
    owner_crew_id: Optional[UUID] = None


class StrategyOKRResponse(StrategyOKRBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    key_results: List["StrategyKeyResultResponse"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# --- Strategy Cycle ---


class StrategyCycleBase(BaseModel):
    name: str
    type: str
    start_date: datetime
    end_date: datetime
    status: Optional[str] = "active"


class StrategyCycleCreate(StrategyCycleBase):
    pass


class StrategyCycleUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None


class StrategyCycleResponse(StrategyCycleBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Strategy Key Result ---


class StrategyKeyResultBase(BaseModel):
    okr_id: UUID
    description: str
    baseline: Optional[float] = None
    target: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None


class StrategyKeyResultCreate(StrategyKeyResultBase):
    pass


class StrategyKeyResultUpdate(BaseModel):
    description: Optional[str] = None
    baseline: Optional[float] = None
    target: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None


class StrategyKeyResultResponse(StrategyKeyResultBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Strategy Initiative ---


class StrategyInitiativeBase(BaseModel):
    title: str
    description: Optional[str] = None
    type: Optional[str] = None
    pillar_id: Optional[UUID] = None
    objective_id: Optional[UUID] = None
    unit: Optional[str] = None
    owner: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = "planned"
    impact: Optional[str] = None
    budget: Optional[float] = None
    risks: Optional[List[str]] = Field(default_factory=list)
    assumptions: Optional[List[str]] = Field(default_factory=list)
    progress: Optional[int] = 0
    space_ids: Optional[List[UUID]] = Field(default_factory=list)
    crew_ids: Optional[List[UUID]] = Field(default_factory=list)


class StrategyInitiativeCreate(StrategyInitiativeBase):
    pass


class StrategyInitiativeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    pillar_id: Optional[UUID] = None
    objective_id: Optional[UUID] = None
    unit: Optional[str] = None
    owner: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None
    impact: Optional[str] = None
    budget: Optional[float] = None
    risks: Optional[List[str]] = None
    assumptions: Optional[List[str]] = None
    progress: Optional[int] = None
    space_ids: Optional[List[UUID]] = None
    crew_ids: Optional[List[UUID]] = None


class StrategyInitiativeResponse(StrategyInitiativeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def map_m2m(cls, data: Any) -> Any:
        """Map ORM M2M relationships to ID lists securely."""
        if not isinstance(data, dict) and hasattr(data, "id"):
            # Use SQLAlchemy inspection to avoid lazy-loading triggers during validation
            try:
                from sqlalchemy import inspect
                state = inspect(data)
                
                # Copy attributes manually to a dict to be safe
                result = {}
                for field in cls.model_fields.keys():
                    if field in ["space_ids", "crew_ids"]:
                        continue
                    if hasattr(data, field):
                        result[field] = getattr(data, field)

                # Map M2M IDs only if they are already loaded
                if "spaces" not in state.unloaded:
                    result["space_ids"] = [s.id for s in data.spaces]
                if "crews" not in state.unloaded:
                    result["crew_ids"] = [c.id for c in data.crews]
                
                # Fill missing keys for Pydantic
                if "space_ids" not in result:
                    result["space_ids"] = []
                if "crew_ids" not in result:
                    result["crew_ids"] = []
                    
                return result
            except Exception:
                # Fallback to defaults or existing object if inspection fails
                pass
        return data


# --- Strategy Assumption ---


class StrategyAssumptionBase(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    impact_score: Optional[int] = 3
    probability_score: Optional[int] = 3
    priority: Optional[str] = None
    impacted_entities: Optional[List[str]] = Field(default_factory=list)
    source: Optional[str] = None
    status: Optional[str] = "identified"
    mitigation_plan: Optional[str] = None
    owner: Optional[str] = None
    linked_objective_id: Optional[UUID] = None
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None


class StrategyAssumptionCreate(StrategyAssumptionBase):
    pass


class StrategyAssumptionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    impact_score: Optional[int] = None
    probability_score: Optional[int] = None
    priority: Optional[str] = None
    impacted_entities: Optional[List[str]] = None
    source: Optional[str] = None
    status: Optional[str] = None
    mitigation_plan: Optional[str] = None
    owner: Optional[str] = None
    linked_objective_id: Optional[UUID] = None


class StrategyAssumptionResponse(StrategyAssumptionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Strategy Health ---


class StrategyHealthResponse(BaseModel):
    coverage_percentage: float
    execution_gap: int
    assumption_risk: int
    cascade_depth: float


class StrategyTreeResponse(BaseModel):
    pillars: List[StrategicPillarResponse]
    objectives: List[StrategicObjectiveResponse]
    okrs: List[StrategyOKRResponse]
    initiatives: List[StrategyInitiativeResponse]
    assumptions: List[StrategyAssumptionResponse]
    cycles: List[StrategyCycleResponse] = Field(default_factory=list)
