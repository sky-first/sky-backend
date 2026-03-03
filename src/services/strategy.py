from datetime import datetime
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

    async def get_strategy_tree(self) -> StrategyTreeResponse:
        pillars = await self.repository.get_all_pillars()
        objectives = await self.repository.get_all_objectives()
        okrs = await self.repository.get_all_okrs()
        initiatives = await self.repository.get_all_initiatives()
        assumptions = await self.repository.get_all_assumptions()

        return StrategyTreeResponse(
            pillars=pillars,
            objectives=objectives,
            okrs=okrs,
            initiatives=initiatives,
            assumptions=assumptions,
        )

    # --- Strategic Pillar ---

    async def create_pillar(self, schema: StrategicPillarCreate) -> StrategicPillarResponse:
        pillar = await self.repository.create_pillar(schema)
        await self.session.commit()
        await self.session.refresh(pillar)
        return pillar

    async def update_pillar(self, pillar_id: UUID, schema: StrategicPillarUpdate) -> StrategicPillarResponse:
        pillar = await self.repository.get_pillar_by_id(pillar_id)
        if not pillar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pillar not found")
        pillar = await self.repository.update_pillar(pillar, schema)
        await self.session.commit()
        await self.session.refresh(pillar)
        return pillar

    async def delete_pillar(self, pillar_id: UUID) -> None:
        pillar = await self.repository.get_pillar_by_id(pillar_id)
        if not pillar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pillar not found")
        await self.repository.delete_pillar(pillar)
        await self.session.commit()

    # --- Strategic Objective ---

    async def create_objective(self, schema: StrategicObjectiveCreate) -> StrategicObjectiveResponse:
        objective = await self.repository.create_objective(schema)
        await self.session.commit()
        await self.session.refresh(objective)
        return objective

    async def update_objective(self, objective_id: UUID, schema: StrategicObjectiveUpdate) -> StrategicObjectiveResponse:
        objective = await self.repository.get_objective_by_id(objective_id)
        if not objective:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
        objective = await self.repository.update_objective(objective, schema)
        await self.session.commit()
        await self.session.refresh(objective)
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
        return okr

    async def update_okr(self, okr_id: UUID, schema: StrategyOKRUpdate) -> StrategyOKRResponse:
        okr = await self.repository.get_okr_by_id(okr_id)
        if not okr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OKR not found")
        okr = await self.repository.update_okr(okr, schema)
        await self.session.commit()
        await self.session.refresh(okr)
        return okr

    async def delete_okr(self, okr_id: UUID) -> None:
        okr = await self.repository.get_okr_by_id(okr_id)
        if not okr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OKR not found")
        await self.repository.delete_okr(okr)
        await self.session.commit()

    # --- Strategy Key Result ---

    async def create_key_result(self, schema: StrategyKeyResultCreate) -> StrategyKeyResultResponse:
        key_result = await self.repository.create_key_result(schema)
        await self.session.commit()
        await self.session.refresh(key_result)
        return key_result

    async def update_key_result(self, key_result_id: UUID, schema: StrategyKeyResultUpdate) -> StrategyKeyResultResponse:
        key_result = await self.repository.get_key_result_by_id(key_result_id)
        if not key_result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key Result not found")
        key_result = await self.repository.update_key_result(key_result, schema)
        await self.session.commit()
        await self.session.refresh(key_result)
        return key_result

    async def delete_key_result(self, key_result_id: UUID) -> None:
        key_result = await self.repository.get_key_result_by_id(key_result_id)
        if not key_result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key Result not found")
        await self.repository.delete_key_result(key_result)
        await self.session.commit()

    # --- Strategy Initiative ---

    async def create_initiative(self, schema: StrategyInitiativeCreate) -> StrategyInitiativeResponse:
        initiative = await self.repository.create_initiative(schema)
        # Auto-compute alignment score
        initiative.alignment_score = self._compute_alignment_score(initiative.supports_objectives)
        await self.session.commit()
        await self.session.refresh(initiative)
        return initiative

    async def update_initiative(self, initiative_id: UUID, schema: StrategyInitiativeUpdate) -> StrategyInitiativeResponse:
        initiative = await self.repository.get_initiative_by_id(initiative_id)
        if not initiative:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
        initiative = await self.repository.update_initiative(initiative, schema)
        # Re-compute alignment score if supports_objectives changed
        if schema.supports_objectives is not None:
            initiative.alignment_score = self._compute_alignment_score(initiative.supports_objectives)
        await self.session.commit()
        await self.session.refresh(initiative)
        return initiative

    async def delete_initiative(self, initiative_id: UUID) -> None:
        initiative = await self.repository.get_initiative_by_id(initiative_id)
        if not initiative:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
        await self.repository.delete_initiative(initiative)
        await self.session.commit()

    # --- Strategy Assumption ---

    async def create_assumption(self, schema: StrategyAssumptionCreate) -> StrategyAssumptionResponse:
        assumption = await self.repository.create_assumption(schema)
        await self.session.commit()
        await self.session.refresh(assumption)
        return assumption

    async def update_assumption(self, assumption_id: UUID, schema: StrategyAssumptionUpdate) -> StrategyAssumptionResponse:
        assumption = await self.repository.get_assumption_by_id(assumption_id)
        if not assumption:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assumption not found")
        assumption = await self.repository.update_assumption(assumption, schema)
        await self.session.commit()
        await self.session.refresh(assumption)
        return assumption

    async def delete_assumption(self, assumption_id: UUID) -> None:
        assumption = await self.repository.get_assumption_by_id(assumption_id)
        if not assumption:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assumption not found")
        await self.repository.delete_assumption(assumption)
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
        assumptions = await self.repository.get_all_assumptions()
        initiatives = await self.repository.get_all_initiatives()

        # 1. Coverage Percentage (% objectives with at least one OKR)
        total_objectives = len(objectives)
        if total_objectives == 0:
            coverage = 0.0
        else:
            objectives_with_okrs = {okr.objective_id for okr in okrs}
            coverage = (len(objectives_with_okrs) / total_objectives) * 100

        # 2. Execution Gap (objectives with 0 initiatives)
        # This requires checking initiative.supports_objectives JSON list
        init_supported_obj_ids = set()
        for init in initiatives:
            if init.supports_objectives:
                for obj_id_str in init.supports_objectives:
                    init_supported_obj_ids.add(str(obj_id_str))
        
        execution_gap = 0
        for obj in objectives:
            if str(obj.id) not in init_supported_obj_ids:
                execution_gap += 1

        # 3. Assumption Risk (number of unvalidated assumptions past deadline)
        now = datetime.now()
        assumption_risk = 0
        for assumption in assumptions:
            if not assumption.validated:
                if assumption.revision_deadline and assumption.revision_deadline.replace(tzinfo=None) < now:
                    assumption_risk += 1

        # 4. Cascade Depth Completeness (Pillar -> Objective -> OKR -> Initiative chain)
        # For now, a simple placeholder based on ratios
        cascade_depth = (coverage / 100.0) * 0.5 + (1.0 - (execution_gap / max(total_objectives, 1))) * 0.5

        return StrategyHealthResponse(
            coverage_percentage=round(coverage, 2),
            execution_gap=execution_gap,
            assumption_risk=assumption_risk,
            cascade_depth_completeness=round(cascade_depth * 100, 2),
        )
