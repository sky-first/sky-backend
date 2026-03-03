from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrategicPillarBase(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    horizon: Optional[str] = None
    owner: Optional[str] = None
    metrics: Optional[List[str]] = Field(default_factory=list)
    priority: Optional[str] = None


class StrategicPillarCreate(StrategicPillarBase):
    pass


class StrategicPillarUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None


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


class StrategicObjectiveCreate(StrategicObjectiveBase):
    pass


class StrategicObjectiveUpdate(BaseModel):
    pillar_id: Optional[UUID] = None
    type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    horizon: Optional[str] = None
    area: Optional[str] = None
    priority: Optional[str] = None
    weight: Optional[float] = None
    owner_crew_id: Optional[UUID] = None


class StrategicObjectiveResponse(StrategicObjectiveBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Strategy OKR ---

class StrategyOKRBase(BaseModel):
    objective_id: UUID
    title: str
    linked_kpi_id: Optional[str] = None
    baseline: Optional[float] = None
    target: Optional[float] = None
    deadline: Optional[datetime] = None
    measurement_frequency: Optional[str] = None
    owner_crew_id: Optional[UUID] = None


class StrategyOKRCreate(StrategyOKRBase):
    pass


class StrategyOKRUpdate(BaseModel):
    objective_id: Optional[UUID] = None
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

    model_config = ConfigDict(from_attributes=True)


# --- Strategy Key Result ---

class StrategyKeyResultBase(BaseModel):
    okr_id: UUID
    description: str
    baseline: Optional[float] = None
    target: Optional[float] = None
    current_value: Optional[float] = 0.0
    unit: Optional[str] = None


class StrategyKeyResultCreate(StrategyKeyResultBase):
    pass


class StrategyKeyResultUpdate(BaseModel):
    okr_id: Optional[UUID] = None
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


class StrategyInitiativeCreate(StrategyInitiativeBase):
    pass


class StrategyInitiativeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    owner_crew_id: Optional[UUID] = None
    budget_estimated: Optional[float] = None
    expected_impact: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    alignment_score: Optional[int] = None
    supports_objectives: Optional[List[UUID]] = None


class StrategyInitiativeResponse(StrategyInitiativeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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


class StrategyAssumptionCreate(StrategyAssumptionBase):
    pass


class StrategyAssumptionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    confidence: Optional[str] = None
    validated: Optional[bool] = None
    revision_deadline: Optional[datetime] = None
    owner_crew_id: Optional[UUID] = None
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
