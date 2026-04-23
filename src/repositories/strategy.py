from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.strategy import (
    StrategicObjective,
    StrategicPillar,
    StrategyAssumption,
    StrategyCycle,
    StrategyInitiative,
    StrategyKeyResult,
    StrategyOKR,
)
from src.schemas.strategy import (
    StrategicObjectiveCreate,
    StrategicObjectiveUpdate,
    StrategicPillarCreate,
    StrategicPillarUpdate,
    StrategyAssumptionCreate,
    StrategyAssumptionUpdate,
    StrategyCycleCreate,
    StrategyCycleUpdate,
    StrategyInitiativeCreate,
    StrategyInitiativeUpdate,
    StrategyKeyResultCreate,
    StrategyKeyResultUpdate,
    StrategyOKRCreate,
    StrategyOKRUpdate,
)


class StrategyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # --- Strategic Pillar ---

    async def get_all_pillars(
        self,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        is_personal: bool = False,
        user_id: Optional[UUID] = None,
    ) -> List[StrategicPillar]:
        query = select(StrategicPillar)
        if is_personal:
            query = query.where(StrategicPillar.owner_user_id == user_id)
        else:
            query = query.where(StrategicPillar.owner_user_id.is_(None))
            if space_id:
                query = query.where(StrategicPillar.space_id == space_id)
            if crew_id:
                query = query.where(StrategicPillar.crew_id == crew_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_pillar_by_id(self, pillar_id: UUID) -> Optional[StrategicPillar]:
        result = await self.session.execute(
            select(StrategicPillar).where(StrategicPillar.id == pillar_id)
        )
        return result.scalar_one_or_none()

    async def create_pillar(self, schema: StrategicPillarCreate) -> StrategicPillar:
        pillar = StrategicPillar(**schema.model_dump())
        self.session.add(pillar)
        await self.session.flush()
        return pillar

    async def update_pillar(
        self, pillar: StrategicPillar, schema: StrategicPillarUpdate
    ) -> StrategicPillar:
        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(pillar, key, value)
        await self.session.flush()
        return pillar

    async def delete_pillar(self, pillar: StrategicPillar) -> None:
        await self.session.delete(pillar)
        await self.session.flush()

    # --- Strategic Objective ---

    async def get_all_objectives(
        self,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        is_personal: bool = False,
        user_id: Optional[UUID] = None,
    ) -> List[StrategicObjective]:
        query = select(StrategicObjective)
        if is_personal:
            query = query.where(StrategicObjective.owner_user_id == user_id)
        else:
            query = query.where(StrategicObjective.owner_user_id.is_(None))
            if space_id:
                query = query.where(StrategicObjective.space_id == space_id)
            if crew_id:
                query = query.where(StrategicObjective.crew_id == crew_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_objective_by_id(self, objective_id: UUID) -> Optional[StrategicObjective]:
        result = await self.session.execute(
            select(StrategicObjective).where(StrategicObjective.id == objective_id)
        )
        return result.scalar_one_or_none()

    async def create_objective(self, schema: StrategicObjectiveCreate) -> StrategicObjective:
        objective = StrategicObjective(**schema.model_dump())
        self.session.add(objective)
        await self.session.flush()
        return objective

    async def update_objective(
        self, objective: StrategicObjective, schema: StrategicObjectiveUpdate
    ) -> StrategicObjective:
        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(objective, key, value)
        await self.session.flush()
        return objective

    async def delete_objective(self, objective: StrategicObjective) -> None:
        await self.session.delete(objective)
        await self.session.flush()

    # --- Strategy OKR ---

    async def get_all_okrs(
        self,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        is_personal: bool = False,
        user_id: Optional[UUID] = None,
    ) -> List[StrategyOKR]:
        query = select(StrategyOKR).options(selectinload(StrategyOKR.key_results))
        if is_personal:
            query = query.where(StrategyOKR.owner_user_id == user_id)
        else:
            query = query.where(StrategyOKR.owner_user_id.is_(None))
            if space_id:
                query = query.where(StrategyOKR.space_id == space_id)
            if crew_id:
                query = query.where(StrategyOKR.crew_id == crew_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_okr_by_id(self, okr_id: UUID) -> Optional[StrategyOKR]:
        result = await self.session.execute(
            select(StrategyOKR)
            .where(StrategyOKR.id == okr_id)
            .options(selectinload(StrategyOKR.key_results))
        )
        return result.scalar_one_or_none()

    async def create_okr(self, schema: StrategyOKRCreate) -> StrategyOKR:
        okr = StrategyOKR(**schema.model_dump())
        self.session.add(okr)
        await self.session.flush()
        return okr

    async def update_okr(self, okr: StrategyOKR, schema: StrategyOKRUpdate) -> StrategyOKR:
        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(okr, key, value)
        await self.session.flush()
        return okr

    async def delete_okr(self, okr: StrategyOKR) -> None:
        await self.session.delete(okr)
        await self.session.flush()

    # --- Strategy Cycle ---

    async def get_all_cycles(self) -> List[StrategyCycle]:
        result = await self.session.execute(select(StrategyCycle))
        return result.scalars().all()

    async def get_cycle_by_id(self, cycle_id: UUID) -> Optional[StrategyCycle]:
        result = await self.session.execute(
            select(StrategyCycle).where(StrategyCycle.id == cycle_id)
        )
        return result.scalar_one_or_none()

    async def create_cycle(self, schema: StrategyCycleCreate) -> StrategyCycle:
        cycle = StrategyCycle(**schema.model_dump())
        self.session.add(cycle)
        await self.session.flush()
        return cycle

    async def update_cycle(
        self, cycle: StrategyCycle, schema: StrategyCycleUpdate
    ) -> StrategyCycle:
        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(cycle, key, value)
        await self.session.flush()
        return cycle

    async def delete_cycle(self, cycle: StrategyCycle) -> None:
        await self.session.delete(cycle)
        await self.session.flush()

    # --- Strategy Key Result ---

    async def get_all_key_results(self) -> List[StrategyKeyResult]:
        result = await self.session.execute(select(StrategyKeyResult))
        return result.scalars().all()

    async def get_key_result_by_id(self, key_result_id: UUID) -> Optional[StrategyKeyResult]:
        result = await self.session.execute(
            select(StrategyKeyResult).where(StrategyKeyResult.id == key_result_id)
        )
        return result.scalar_one_or_none()

    async def create_key_result(self, schema: StrategyKeyResultCreate) -> StrategyKeyResult:
        key_result = StrategyKeyResult(**schema.model_dump())
        self.session.add(key_result)
        await self.session.flush()
        return key_result

    async def update_key_result(
        self, key_result: StrategyKeyResult, schema: StrategyKeyResultUpdate
    ) -> StrategyKeyResult:
        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(key_result, key, value)
        await self.session.flush()
        return key_result

    async def delete_key_result(self, key_result: StrategyKeyResult) -> None:
        await self.session.delete(key_result)
        await self.session.flush()

    # --- Strategy Initiative ---
    async def get_all_initiatives(
        self, space_id: Optional[UUID] = None, crew_id: Optional[UUID] = None
    ) -> List[StrategyInitiative]:
        from src.models.crew import Crew
        from src.models.space import Space

        query = (
            select(StrategyInitiative)
            .options(
                selectinload(StrategyInitiative.spaces),
                selectinload(StrategyInitiative.crews)
            )
        )
        if space_id:
            query = query.join(StrategyInitiative.spaces).where(Space.id == space_id)
        if crew_id:
            query = query.join(StrategyInitiative.crews).where(Crew.id == crew_id)

        # Cannot use plain .distinct() — StrategyInitiative has json columns
        # (risks, assumptions) and Postgres has no equality operator for the
        # json type, so SELECT DISTINCT crashes with UndefinedFunctionError.
        # The joins above can produce duplicates when an initiative has many
        # spaces/crews; dedupe on .id in Python after the query instead.
        result = await self.session.execute(query)
        all_rows = result.scalars().all()
        seen: set = set()
        unique: list[StrategyInitiative] = []
        for row in all_rows:
            if row.id in seen:
                continue
            seen.add(row.id)
            unique.append(row)
        return unique

    async def get_initiative_by_id(self, initiative_id: UUID) -> Optional[StrategyInitiative]:
        result = await self.session.execute(
            select(StrategyInitiative)
            .options(
                selectinload(StrategyInitiative.spaces),
                selectinload(StrategyInitiative.crews)
            )
            .where(StrategyInitiative.id == initiative_id)
        )
        return result.scalar_one_or_none()

    async def create_initiative(self, schema: StrategyInitiativeCreate) -> StrategyInitiative:
        from src.models.crew import Crew
        from src.models.space import Space

        data = schema.model_dump(exclude={"space_ids", "crew_ids"})
        initiative = StrategyInitiative(**data)
        
        # Load and associate spaces
        if schema.space_ids:
            res = await self.session.execute(select(Space).where(Space.id.in_(schema.space_ids)))
            initiative.spaces = list(res.scalars().all())
            
        # Load and associate crews
        if schema.crew_ids:
            res = await self.session.execute(select(Crew).where(Crew.id.in_(schema.crew_ids)))
            initiative.crews = list(res.scalars().all())

        self.session.add(initiative)
        await self.session.flush()
        # Reload with relationships for the response schema
        res = await self.session.execute(
            select(StrategyInitiative)
            .options(
                selectinload(StrategyInitiative.spaces),
                selectinload(StrategyInitiative.crews)
            )
            .where(StrategyInitiative.id == initiative.id)
        )
        return res.scalar_one()

    async def update_initiative(
        self, initiative: StrategyInitiative, schema: StrategyInitiativeUpdate
    ) -> StrategyInitiative:
        from src.models.crew import Crew
        from src.models.space import Space

        update_data = schema.model_dump(exclude_unset=True, exclude={"space_ids", "crew_ids"})
        for key, value in update_data.items():
            setattr(initiative, key, value)
            
        # Update M2M relationships if provided
        if schema.space_ids is not None:
            res = await self.session.execute(select(Space).where(Space.id.in_(schema.space_ids)))
            initiative.spaces = list(res.scalars().all())
            
        if schema.crew_ids is not None:
            res = await self.session.execute(select(Crew).where(Crew.id.in_(schema.crew_ids)))
            initiative.crews = list(res.scalars().all())

        await self.session.flush()
        # Reload with relationships for the response schema
        res = await self.session.execute(
            select(StrategyInitiative)
            .options(
                selectinload(StrategyInitiative.spaces),
                selectinload(StrategyInitiative.crews)
            )
            .where(StrategyInitiative.id == initiative.id)
        )
        return res.scalar_one()

    async def delete_initiative(self, initiative: StrategyInitiative) -> None:
        await self.session.delete(initiative)
        await self.session.flush()

    # --- Strategy Assumption ---

    async def get_all_assumptions(self, space_id: Optional[UUID] = None, crew_id: Optional[UUID] = None) -> List[StrategyAssumption]:
        query = select(StrategyAssumption)
        if space_id:
            query = query.where(StrategyAssumption.space_id == space_id)
        if crew_id:
            query = query.where(StrategyAssumption.crew_id == crew_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_assumption_by_id(self, assumption_id: UUID) -> Optional[StrategyAssumption]:
        result = await self.session.execute(
            select(StrategyAssumption).where(StrategyAssumption.id == assumption_id)
        )
        return result.scalar_one_or_none()

    async def create_assumption(self, schema: StrategyAssumptionCreate) -> StrategyAssumption:
        assumption = StrategyAssumption(**schema.model_dump())
        self.session.add(assumption)
        await self.session.flush()
        return assumption

    async def update_assumption(
        self, assumption: StrategyAssumption, schema: StrategyAssumptionUpdate
    ) -> StrategyAssumption:
        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(assumption, key, value)
        await self.session.flush()
        return assumption

    async def delete_assumption(self, assumption: StrategyAssumption) -> None:
        await self.session.delete(assumption)
        await self.session.flush()
