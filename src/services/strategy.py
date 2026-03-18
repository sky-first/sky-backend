from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.strategy import StrategyRepository
from src.schemas.strategy import (
    StrategicObjectiveCreate,
    StrategicObjectiveResponse,
    StrategicObjectiveUpdate,
    StrategicPillarCreate,
    StrategicPillarResponse,
    StrategicPillarUpdate,
    StrategyAssumptionCreate,
    StrategyAssumptionResponse,
    StrategyAssumptionUpdate,
    StrategyCycleCreate,
    StrategyCycleResponse,
    StrategyCycleUpdate,
    StrategyHealthResponse,
    StrategyInitiativeCreate,
    StrategyInitiativeResponse,
    StrategyInitiativeUpdate,
    StrategyKeyResultCreate,
    StrategyKeyResultResponse,
    StrategyKeyResultUpdate,
    StrategyOKRCreate,
    StrategyOKRResponse,
    StrategyOKRUpdate,
    StrategyTreeResponse,
)


class StrategyService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = StrategyRepository(session)
        from src.ai.http_client import AIServiceHTTPClient
        self.ai_client = AIServiceHTTPClient()

    async def _trigger_ai_ingestion(self, entity: Any, entity_type: str):
        """Helper to trigger AI ingestion for an entity."""
        try:
            payload = {
                "id": str(entity.id),
                "entity_type": entity_type,
                "name": getattr(entity, "name", getattr(entity, "title", None)),
                "description": getattr(entity, "description", None),
                "space_id": str(entity.space_id) if hasattr(entity, 'space_id') and entity.space_id else None,
                "crew_id": str(entity.crew_id) if hasattr(entity, 'crew_id') and entity.crew_id else None,
                "entity_details": {
                    "status": getattr(entity, "status", None),
                    "priority": getattr(entity, "priority", None),
                }
            }
            # Add specific details based on type
            if entity_type == "strategy_okr":
                payload["entity_details"]["objective_id"] = str(entity.objective_id)
            elif entity_type == "strategic_objective":
                payload["entity_details"]["pillar_id"] = str(entity.pillar_id) if entity.pillar_id else None
            
            await self.ai_client.ingest_knowledge_graph(payload)
        except Exception as e:
            from src.services.enterprise_relationship_service import logger
            logger.error(f"Failed to trigger AI ingestion for {entity_type} {entity.id}: {e}")

    async def get_strategy_tree(self) -> StrategyTreeResponse:
        pillars = await self.repository.get_all_pillars()
        objectives = await self.repository.get_all_objectives()
        okrs = await self.repository.get_all_okrs()
        initiatives = await self.repository.get_all_initiatives()
        assumptions = await self.repository.get_all_assumptions()
        cycles = await self.repository.get_all_cycles()

        return StrategyTreeResponse(
            pillars=pillars,
            objectives=objectives,
            okrs=okrs,
            initiatives=initiatives,
            assumptions=assumptions,
            cycles=cycles,
        )

    # --- Strategic Pillar ---

    async def create_pillar(self, schema: StrategicPillarCreate) -> StrategicPillarResponse:
        pillar = await self.repository.create_pillar(schema)
        await self.session.commit()
        await self.session.refresh(pillar)
        await self._trigger_ai_ingestion(pillar, "strategic_pillar")
        return pillar

    async def update_pillar(
        self, pillar_id: UUID, schema: StrategicPillarUpdate
    ) -> StrategicPillarResponse:
        pillar = await self.repository.get_pillar_by_id(pillar_id)
        if not pillar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pillar not found")
        pillar = await self.repository.update_pillar(pillar, schema)
        await self.session.commit()
        await self.session.refresh(pillar)
        await self._trigger_ai_ingestion(pillar, "strategic_pillar")
        return pillar

    async def delete_pillar(self, pillar_id: UUID) -> None:
        pillar = await self.repository.get_pillar_by_id(pillar_id)
        if not pillar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pillar not found")
        await self.repository.delete_pillar(pillar)
        await self.session.commit()

    # --- Strategic Objective ---

    async def create_objective(
        self, schema: StrategicObjectiveCreate
    ) -> StrategicObjectiveResponse:
        objective = await self.repository.create_objective(schema)
        await self.session.commit()
        await self.session.refresh(objective)
        await self._trigger_ai_ingestion(objective, "strategic_objective")
        return objective

    async def update_objective(
        self, objective_id: UUID, schema: StrategicObjectiveUpdate
    ) -> StrategicObjectiveResponse:
        objective = await self.repository.get_objective_by_id(objective_id)
        if not objective:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
        objective = await self.repository.update_objective(objective, schema)
        await self.session.commit()
        await self.session.refresh(objective)
        await self._trigger_ai_ingestion(objective, "strategic_objective")
        return objective

    async def delete_objective(self, objective_id: UUID) -> None:
        objective = await self.repository.get_objective_by_id(objective_id)
        if not objective:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
        await self.repository.delete_objective(objective)
        await self.session.commit()

    # --- Strategy OKR ---

    async def create_okr(self, schema: StrategyOKRCreate) -> StrategyOKRResponse:
        okr = await self.repository.create_okr(schema)
        await self.session.commit()
        await self.session.refresh(okr)
        await self._trigger_ai_ingestion(okr, "strategy_okr")
        return okr

    async def update_okr(self, okr_id: UUID, schema: StrategyOKRUpdate) -> StrategyOKRResponse:
        okr = await self.repository.get_okr_by_id(okr_id)
        if not okr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OKR not found")
        okr = await self.repository.update_okr(okr, schema)
        await self.session.commit()
        await self.session.refresh(okr)
        await self._trigger_ai_ingestion(okr, "strategy_okr")
        return okr

    async def delete_okr(self, okr_id: UUID) -> None:
        okr = await self.repository.get_okr_by_id(okr_id)
        if not okr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OKR not found")
        await self.repository.delete_okr(okr)
        await self.session.commit()



    # --- Strategy Initiative ---

    async def create_initiative(
        self, schema: StrategyInitiativeCreate
    ) -> StrategyInitiativeResponse:
        initiative = await self.repository.create_initiative(schema)
        # Compute progress initial (0) or from schema
        await self.session.commit()
        await self.session.refresh(initiative)
        await self._trigger_ai_ingestion(initiative, "strategy_initiative")
        return initiative

    async def update_initiative(
        self, initiative_id: UUID, schema: StrategyInitiativeUpdate
    ) -> StrategyInitiativeResponse:
        initiative = await self.repository.get_initiative_by_id(initiative_id)
        if not initiative:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found"
            )
        initiative = await self.repository.update_initiative(initiative, schema)
        await self.session.commit()
        await self.session.refresh(initiative)
        await self._trigger_ai_ingestion(initiative, "strategy_initiative")
        return initiative

    async def delete_initiative(self, initiative_id: UUID) -> None:
        initiative = await self.repository.get_initiative_by_id(initiative_id)
        if not initiative:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found"
            )
        await self.repository.delete_initiative(initiative)
        await self.session.commit()

    # --- Strategy Assumption ---

    async def create_assumption(self, schema: StrategyAssumptionCreate) -> StrategyAssumptionResponse:
        assumption = await self.repository.create_assumption(schema)
        await self.session.commit()
        await self.session.refresh(assumption)
        await self._trigger_ai_ingestion(assumption, "strategy_assumption")
        return assumption

    async def update_assumption(
        self, assumption_id: UUID, schema: StrategyAssumptionUpdate
    ) -> StrategyAssumptionResponse:
        assumption = await self.repository.get_assumption_by_id(assumption_id)
        if not assumption:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assumption not found")
        assumption = await self.repository.update_assumption(assumption, schema)
        await self.session.commit()
        await self.session.refresh(assumption)
        await self._trigger_ai_ingestion(assumption, "strategy_assumption")
        return assumption

    async def delete_assumption(self, assumption_id: UUID) -> None:
        assumption = await self.repository.get_assumption_by_id(assumption_id)
        if not assumption:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assumption not found")
        await self.repository.delete_assumption(assumption)
        await self.session.commit()

    # --- Strategy Cycle ---

    async def create_cycle(self, schema: StrategyCycleCreate) -> StrategyCycleResponse:
        cycle = await self.repository.create_cycle(schema)
        await self.session.commit()
        await self.session.refresh(cycle)
        return cycle

    async def update_cycle(self, cycle_id: UUID, schema: StrategyCycleUpdate) -> StrategyCycleResponse:
        cycle = await self.repository.get_cycle_by_id(cycle_id)
        if not cycle:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle not found")
        cycle = await self.repository.update_cycle(cycle, schema)
        await self.session.commit()
        await self.session.refresh(cycle)
        return cycle

    async def delete_cycle(self, cycle_id: UUID) -> None:
        cycle = await self.repository.get_cycle_by_id(cycle_id)
        if not cycle:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle not found")
        await self.repository.delete_cycle(cycle)
        await self.session.commit()

    # --- Strategy Key Result ---

    async def create_key_result(self, schema: StrategyKeyResultCreate) -> StrategyKeyResultResponse:
        kr = await self.repository.create_key_result(schema)
        await self.session.commit()
        await self.session.refresh(kr)
        return kr

    async def update_key_result(
        self, kr_id: UUID, schema: StrategyKeyResultUpdate
    ) -> StrategyKeyResultResponse:
        kr = await self.repository.get_key_result_by_id(kr_id)
        if not kr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key Result not found")
        kr = await self.repository.update_key_result(kr, schema)
        await self.session.commit()
        await self.session.refresh(kr)
        return kr

    async def delete_key_result(self, kr_id: UUID) -> None:
        kr = await self.repository.get_key_result_by_id(kr_id)
        if not kr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key Result not found")
        await self.repository.delete_key_result(kr)
        await self.session.commit()



    # --- Business Logic ---

    def _compute_alignment_score(self, supports_objectives: list) -> int:
        if not supports_objectives:
            return 0
        # Simple logic: 20 points per objective supported, cap at 100
        return min(len(supports_objectives) * 20, 100)

    async def get_strategy_health(self) -> StrategyHealthResponse:
        objectives = await self.repository.get_all_objectives()
        okrs = await self.repository.get_all_okrs()
        initiatives = await self.repository.get_all_initiatives()
        assumptions = await self.repository.get_all_assumptions()

        # 1. Coverage Percentage (% objectives with at least one OKR)
        total_objectives = len(objectives)
        if total_objectives == 0:
            coverage = 0.0
        else:
            objectives_with_okrs = {okr.objective_id for okr in okrs}
            coverage = (len(objectives_with_okrs) / total_objectives) * 100

        # 2. Execution Velocity (Average progress of all initiatives)
        total_progress = sum(init.progress for init in initiatives if init.progress is not None)
        velocity = (total_progress / len(initiatives)) if initiatives else 100.0

        # 3. Risk Exposure (Calculated from assumptions)
        if assumptions:
            total_impact = sum(a.impact_score * a.probability_score for a in assumptions)
            risk_exposure = (total_impact / (len(assumptions) * 25)) * 100  # Max score is 5*5=25
        else:
            risk_exposure = 0

        # 4. Cascade Depth (Completeness of links: Pillar -> Objective -> Initiative)
        cascade_depth = 0.0
        if total_objectives > 0:
            linked_count = sum(1 for obj in objectives if obj.pillar_id is not None)
            cascade_depth = (linked_count / total_objectives) * 100

        return StrategyHealthResponse(
            coverage_percentage=round(coverage, 2),
            execution_gap=int(velocity),
            assumption_risk=int(risk_exposure),
            cascade_depth=round(cascade_depth, 2),
        )
