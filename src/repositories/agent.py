"""Agent repository for database operations."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.agent import Agent, AgentExecution, AgentFinding
from src.repositories.base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, Agent)

    async def get_with_findings(self, agent_id: UUID) -> Optional[Agent]:
        result = await self.db.execute(
            select(Agent)
            .options(selectinload(Agent.findings))
            .where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def list_by_scope(
        self,
        scope: Optional[str] = None,
        scope_id: Optional[str] = None,
        created_by: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Agent]:
        # Findings are NOT eager-loaded here. Loading them on every list
        # call caused 62 concurrent heavy queries to exhaust the DB
        # connection pool when the frontend fetched agents for every space.
        # The frontend missions store uses the findings returned by
        # GET /{agent_id} (get_with_findings) for the cockpit/halo detail
        # view. The list endpoint only needs the agent metadata.
        query = select(Agent)
        if scope:
            query = query.where(Agent.scope == scope)
        if scope_id:
            query = query.where(Agent.scope_id == scope_id)
        if created_by:
            query = query.where(Agent.created_by == created_by)
        query = query.order_by(Agent.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        agentes = list(result.scalars().all())
        await self._anexar_sinais_de_vida(agentes)
        return agentes

    async def _anexar_sinais_de_vida(self, agentes: List[Agent]) -> None:
        """Põe em cada agente o último achado e o estado da última corrida.

        **Porque isto existe.** A lista devolvia o que cada agente É — nome,
        pergunta, cadência — e nada sobre o que ele TEM FEITO. No ecrã lia-se
        como uma tabela de tarefas agendadas: nomes e horários, sem sinal de
        vida. E um agente activo que falha em silêncio lia-se igual a um que
        está a correr bem, o que é pior do que um parado — o parado ao menos
        diz que está parado.

        **Duas consultas agregadas, e não uma por agente.** O comentário do
        `list_by_scope` explica porquê: carregar achados por agente esgotou a
        pousada de ligações quando a web pediu agentes para todos os projetos
        de uma vez. Aqui usa-se `row_number()` com partição — uma consulta
        para o último achado, outra para a última execução — e ambas param
        na primeira linha de cada agente.

        Os campos são postos NA INSTÂNCIA e não são colunas: o `AgentResponse`
        lê-os por atributo (`from_attributes`), e assim não há migração.
        """
        if not agentes:
            return

        ids = [a.id for a in agentes]

        # Cada modelo tem o SEU carimbo temporal, e não o mesmo: os achados
        # datam-se por `created_at`, as execuções por `started_at`. Escrevi
        # `created_at` para os dois e um teste do RBAC apanhou-o de imediato —
        # `AgentExecution` nem sequer tem essa coluna.
        def _ultimo(modelo, quando, *colunas):
            n = (
                func.row_number()
                .over(partition_by=modelo.agent_id, order_by=quando.desc())
                .label("n")
            )
            sub = (
                select(modelo.agent_id, *colunas, quando.label("quando"), n)
                .where(modelo.agent_id.in_(ids))
                .subquery()
            )
            return select(sub).where(sub.c.n == 1)

        achados = (
            await self.db.execute(
                _ultimo(AgentFinding, AgentFinding.created_at, AgentFinding.title)
            )
        ).all()
        por_agente = {linha[0]: linha for linha in achados}

        execucoes = (
            await self.db.execute(
                _ultimo(AgentExecution, AgentExecution.started_at, AgentExecution.status)
            )
        ).all()
        estado_por_agente = {linha[0]: linha[1] for linha in execucoes}

        for a in agentes:
            achado = por_agente.get(a.id)
            a.last_finding_title = achado[1] if achado else None
            a.last_finding_at = achado[2] if achado else None
            a.last_run_status = estado_por_agente.get(a.id)

    async def list_active_for_execution(self) -> List[Agent]:
        """Get all active agents that need execution."""
        result = await self.db.execute(
            select(Agent).where(Agent.status == "active")
        )
        return list(result.scalars().all())


class AgentFindingRepository(BaseRepository[AgentFinding]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentFinding)

    async def list_by_agent(
        self,
        agent_id: UUID,
        include_dismissed: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> List[AgentFinding]:
        query = select(AgentFinding).where(AgentFinding.agent_id == agent_id)
        if not include_dismissed:
            query = query.where(AgentFinding.dismissed == False)
        query = query.order_by(AgentFinding.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def dismiss(self, finding_id: UUID) -> Optional[AgentFinding]:
        from datetime import datetime, timezone
        await self.db.execute(
            update(AgentFinding)
            .where(AgentFinding.id == finding_id)
            .values(dismissed=True, dismissed_at=datetime.now(timezone.utc))
        )
        await self.db.commit()
        return await self.get_by_id(finding_id)


class AgentExecutionRepository(BaseRepository[AgentExecution]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentExecution)
