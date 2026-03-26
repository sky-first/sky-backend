import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
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

logger = logging.getLogger(__name__)


class StrategyService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = StrategyRepository(session)
        from src.ai.http_client import AIServiceHTTPClient

        self.ai_client = AIServiceHTTPClient()

    def _trigger_ai_ingestion(self, entity: Any, entity_type: str, background_tasks: BackgroundTasks):
        """Helper to trigger AI ingestion for an entity in the background using BackgroundTasks."""
        try:
            # Handle M2M objects vs single space_id/crew_id
            space_val = None
            if hasattr(entity, "spaces") and entity.spaces:
                space_val = str(entity.spaces[0].id)
            elif hasattr(entity, "space_id") and entity.space_id:
                space_val = str(entity.space_id)
            elif hasattr(entity, "space_ids") and entity.space_ids:
                space_val = str(entity.space_ids[0])
                
            crew_val = None
            if hasattr(entity, "crews") and entity.crews:
                crew_val = str(entity.crews[0].id)
            elif hasattr(entity, "crew_id") and entity.crew_id:
                crew_val = str(entity.crew_id)
            elif hasattr(entity, "crew_ids") and entity.crew_ids:
                crew_val = str(entity.crew_ids[0])

            payload = {
                "id": str(entity.id),
                "entity_type": entity_type,
                "name": getattr(entity, "name", getattr(entity, "title", None)),
                "description": getattr(entity, "description", None),
                "space_id": space_val,
                "crew_id": crew_val,
                "entity_details": {
                    "status": getattr(entity, "status", None),
                    "priority": getattr(entity, "priority", None),
                },
            }
            # Add specific details based on type
            if entity_type == "strategy_okr":
                payload["entity_details"]["objective_id"] = str(entity.objective_id)
            elif entity_type == "strategic_objective":
                payload["entity_details"]["pillar_id"] = (
                    str(entity.pillar_id) if entity.pillar_id else None
                )

            background_tasks.add_task(self._background_ingest_task, payload, entity_type, str(entity.id))
        except Exception as e:
            logger.error(f"Failed to schedule AI ingestion for {entity_type} {entity.id}: {e}")

    async def _background_ingest_task(self, payload: dict, entity_type: str, entity_id: str) -> None:
        """Helper to ingest entity into Knowledge Graph with proper error handling for BackgroundTasks."""
        try:
            await self.ai_client.ingest_knowledge_graph(payload)
        except Exception as e:
            logger.error(f"Background task failed: AI ingestion for {entity_type} {entity_id} failed: {e}")

    async def get_strategy_tree(
        self, space_id: Optional[UUID] = None, crew_id: Optional[UUID] = None
    ) -> StrategyTreeResponse:
        pillars = await self.repository.get_all_pillars(space_id=space_id, crew_id=crew_id)
        objectives = await self.repository.get_all_objectives(space_id=space_id, crew_id=crew_id)
        okrs = await self.repository.get_all_okrs(space_id=space_id, crew_id=crew_id)
        initiatives = await self.repository.get_all_initiatives(space_id=space_id, crew_id=crew_id)
        assumptions = await self.repository.get_all_assumptions(space_id=space_id, crew_id=crew_id)
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

    async def create_pillar(
        self, schema: StrategicPillarCreate, background_tasks: BackgroundTasks
    ) -> StrategicPillarResponse:
        pillar = await self.repository.create_pillar(schema)
        await self.session.commit()
        await self.session.refresh(pillar)
        self._trigger_ai_ingestion(pillar, "strategic_pillar", background_tasks)
        return pillar

    async def update_pillar(
        self, pillar_id: UUID, schema: StrategicPillarUpdate, background_tasks: BackgroundTasks
    ) -> StrategicPillarResponse:
        pillar = await self.repository.get_pillar_by_id(pillar_id)
        if not pillar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pillar not found")
        pillar = await self.repository.update_pillar(pillar, schema)
        await self.session.commit()
        await self.session.refresh(pillar)
        self._trigger_ai_ingestion(pillar, "strategic_pillar", background_tasks)
        return pillar

    async def delete_pillar(self, pillar_id: UUID) -> None:
        pillar = await self.repository.get_pillar_by_id(pillar_id)
        if not pillar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pillar not found")
        await self.repository.delete_pillar(pillar)
        await self.session.commit()

    # --- Strategic Objective ---

    async def create_objective(
        self, schema: StrategicObjectiveCreate, background_tasks: BackgroundTasks
    ) -> StrategicObjectiveResponse:
        objective = await self.repository.create_objective(schema)
        await self.session.commit()
        await self.session.refresh(objective)
        self._trigger_ai_ingestion(objective, "strategic_objective", background_tasks)
        return objective

    async def update_objective(
        self, objective_id: UUID, schema: StrategicObjectiveUpdate, background_tasks: BackgroundTasks
    ) -> StrategicObjectiveResponse:
        objective = await self.repository.get_objective_by_id(objective_id)
        if not objective:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
        objective = await self.repository.update_objective(objective, schema)
        await self.session.commit()
        await self.session.refresh(objective)
        self._trigger_ai_ingestion(objective, "strategic_objective", background_tasks)
        return objective

    async def delete_objective(self, objective_id: UUID) -> None:
        objective = await self.repository.get_objective_by_id(objective_id)
        if not objective:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
        await self.repository.delete_objective(objective)
        await self.session.commit()

    # --- Strategy OKR ---

    async def create_okr(
        self, schema: StrategyOKRCreate, background_tasks: BackgroundTasks
    ) -> StrategyOKRResponse:
        okr = await self.repository.create_okr(schema)
        await self.session.commit()
        okr = await self.repository.get_okr_by_id(okr.id)
        self._trigger_ai_ingestion(okr, "strategy_okr", background_tasks)
        return okr

    async def update_okr(
        self, okr_id: UUID, schema: StrategyOKRUpdate, background_tasks: BackgroundTasks
    ) -> StrategyOKRResponse:
        okr = await self.repository.get_okr_by_id(okr_id)
        if not okr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OKR not found")
        okr = await self.repository.update_okr(okr, schema)
        await self.session.commit()
        okr = await self.repository.get_okr_by_id(okr.id)
        self._trigger_ai_ingestion(okr, "strategy_okr", background_tasks)
        return okr

    async def delete_okr(self, okr_id: UUID) -> None:
        okr = await self.repository.get_okr_by_id(okr_id)
        if not okr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OKR not found")
        await self.repository.delete_okr(okr)
        await self.session.commit()

    # --- Strategy Initiative ---

    async def create_initiative(
        self, schema: StrategyInitiativeCreate, background_tasks: BackgroundTasks
    ) -> StrategyInitiativeResponse:
        initiative = await self.repository.create_initiative(schema)
        await self.session.commit()
        # Trigger ingestion manually to skip refresh wait if possible
        try:
            payload = {
                "id": str(initiative.id),
                "entity_type": "strategy_initiative",
                "name": initiative.title,
                "description": initiative.description,
                "status": "in_progress",
                "space_id": str(initiative.spaces[0].id) if hasattr(initiative, "spaces") and initiative.spaces else None,
                "crew_id": str(initiative.crews[0].id) if hasattr(initiative, "crews") and initiative.crews else None
            }
            background_tasks.add_task(self.ai_client.ingest_knowledge_graph, payload)
        except Exception as e:
            logger.error(f"Failed to trigger initial ingestion for initiative: {e}")
        return initiative

    async def update_initiative(
        self, initiative_id: UUID, schema: StrategyInitiativeUpdate, background_tasks: BackgroundTasks
    ) -> StrategyInitiativeResponse:
        initiative = await self.repository.get_initiative_by_id(initiative_id)
        if not initiative:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found"
            )
        initiative = await self.repository.update_initiative(initiative, schema)
        await self.session.commit()
        # We don't refresh to avoid losing M2M objects that were selectinloaded
        # but we do refresh basic fields if needed.
        # However, the repo already returned the fresh object.
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

    async def create_assumption(
        self, schema: StrategyAssumptionCreate, background_tasks: BackgroundTasks
    ) -> StrategyAssumptionResponse:
        assumption = await self.repository.create_assumption(schema)
        await self.session.commit()
        await self.session.refresh(assumption)
        self._trigger_ai_ingestion(assumption, "strategy_assumption", background_tasks)
        return assumption

    async def update_assumption(
        self, assumption_id: UUID, schema: StrategyAssumptionUpdate, background_tasks: BackgroundTasks
    ) -> StrategyAssumptionResponse:
        assumption = await self.repository.get_assumption_by_id(assumption_id)
        if not assumption:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assumption not found"
            )
        assumption = await self.repository.update_assumption(assumption, schema)
        await self.session.commit()
        await self.session.refresh(assumption)
        self._trigger_ai_ingestion(assumption, "strategy_assumption", background_tasks)
        return assumption

    async def delete_assumption(self, assumption_id: UUID) -> None:
        assumption = await self.repository.get_assumption_by_id(assumption_id)
        if not assumption:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assumption not found"
            )
        await self.repository.delete_assumption(assumption)
        await self.session.commit()

    # --- Strategy Cycle ---

    async def create_cycle(
        self, schema: StrategyCycleCreate, background_tasks: BackgroundTasks
    ) -> StrategyCycleResponse:
        cycle = await self.repository.create_cycle(schema)
        await self.session.commit()
        await self.session.refresh(cycle)
        self._trigger_ai_ingestion(cycle, "strategy_cycle", background_tasks)
        return cycle

    async def update_cycle(
        self, cycle_id: UUID, schema: StrategyCycleUpdate, background_tasks: BackgroundTasks
    ) -> StrategyCycleResponse:
        cycle = await self.repository.get_cycle_by_id(cycle_id)
        if not cycle:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle not found")
        cycle = await self.repository.update_cycle(cycle, schema)
        await self.session.commit()
        await self.session.refresh(cycle)
        self._trigger_ai_ingestion(cycle, "strategy_cycle", background_tasks)
        return cycle

    async def delete_cycle(self, cycle_id: UUID) -> None:
        cycle = await self.repository.get_cycle_by_id(cycle_id)
        if not cycle:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle not found")
        await self.repository.delete_cycle(cycle)
        await self.session.commit()

    # --- Strategy Key Result ---

    async def create_key_result(
        self, schema: StrategyKeyResultCreate, background_tasks: BackgroundTasks
    ) -> StrategyKeyResultResponse:
        kr = await self.repository.create_key_result(schema)
        await self.session.commit()
        await self.session.refresh(kr)
        self._trigger_ai_ingestion(kr, "strategy_key_result", background_tasks)
        return kr

    async def update_key_result(
        self, kr_id: UUID, schema: StrategyKeyResultUpdate, background_tasks: BackgroundTasks
    ) -> StrategyKeyResultResponse:
        kr = await self.repository.get_key_result_by_id(kr_id)
        if not kr:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Key Result not found"
            )
        kr = await self.repository.update_key_result(kr, schema)
        await self.session.commit()
        await self.session.refresh(kr)
        self._trigger_ai_ingestion(kr, "strategy_key_result", background_tasks)
        return kr

    async def delete_key_result(self, kr_id: UUID) -> None:
        kr = await self.repository.get_key_result_by_id(kr_id)
        if not kr:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Key Result not found"
            )
        await self.repository.delete_key_result(kr)
        await self.session.commit()

    # --- Business Logic ---

    async def get_strategy_health(
        self, space_id: Optional[UUID] = None, crew_id: Optional[UUID] = None
    ) -> StrategyHealthResponse:
        objectives = await self.repository.get_all_objectives(space_id=space_id, crew_id=crew_id)
        okrs = await self.repository.get_all_okrs(space_id=space_id, crew_id=crew_id)
        initiatives = await self.repository.get_all_initiatives(space_id=space_id, crew_id=crew_id)
        assumptions = await self.repository.get_all_assumptions(space_id=space_id, crew_id=crew_id)

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

        # 3. Risk Exposure (Sum of impact * probability of active assumptions as risks)
        risk_exposure = 0
        active_risks = [r for r in assumptions if r.status in ["identified", "materialized"]]
        if active_risks:
            max_possible_risk = len(active_risks) * 25  # 5 * 5
            total_current_risk = sum(
                (r.impact_score or 0) * (r.probability_score or 0) for r in active_risks
            )
            risk_exposure = (total_current_risk / max_possible_risk) * 100

        # 4. Cascade Depth (Completeness of links: Pillar -> Objective)
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
