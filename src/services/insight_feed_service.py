"""Unified mobile Insights feed (BE-02, Sky Mobile).

Serves one machine-readable object per finding, unifying two sources:

* **agent** findings — attached to a registered ``Agent`` (scoped via that
  agent's Space/Crew), and
* **scan** findings — produced by the autonomous scan agent, carrying
  ``space_id`` directly (``agent_id`` is NULL).

Every read is scoped to the caller's **content plane** — the Spaces and Crews
they are actually a member of (no platform-role bypass; identical rule to the
legacy ``/agents/insights/all``). Pagination is a stable **keyset cursor** on
``(created_at DESC, id DESC)`` so inserts mid-paging never cause dupes or gaps.
Per-user ``reviewed``/``pinned`` state is joined from ``insight_state``.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import Agent, AgentFinding
from src.models.crew import Crew, CrewMember
from src.models.insight_state import InsightState
from src.models.space import SpaceMember
from src.schemas.insight_feed import InsightDetail, InsightFeedResponse, InsightItem

# A scan finding is "live" while it is recent (scans run every 1-24h); an agent
# finding is "live" while its agent is active + recently executed. Honest: this
# is "an agent is watching this", not a real-time metric stream.
_SCAN_LIVE_WINDOW = timedelta(hours=25)
_AGENT_LIVE_WINDOW = timedelta(days=2)


class InvalidCursor(Exception):
    """Raised for a malformed pagination cursor → the endpoint returns 400."""


class InsightFeedService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Scope (content plane) ───────────────────────────────────────────

    async def _member_scope(self, user_id: UUID) -> Tuple[List[UUID], List[UUID]]:
        space_ids = list(
            (
                await self.db.execute(
                    select(SpaceMember.space_id).where(SpaceMember.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        crew_ids = list(
            (await self.db.execute(select(CrewMember.crew_id).where(CrewMember.user_id == user_id)))
            .scalars()
            .all()
        )
        return space_ids, crew_ids

    def _scope_where(
        self,
        user_id: UUID,
        space_ids: List[UUID],
        crew_ids: List[UUID],
        space_id: Optional[UUID] = None,
    ):
        """A finding is visible when it is a scan finding in one of my Spaces,
        OR an agent finding I own / whose Space or Crew I belong to.

        Com ``space_id``, o feed é DAQUELE projeto e não de tudo o que a
        pessoa alcança.

        Sem isto, o feed respondia a «o que é que EU posso ver?» em vez de «o
        que há NESTE projeto?»: bastava o achado ser de um agente meu para
        aparecer em todos os projetos, incluindo os que não têm uma única
        ligação de dados. Não era fuga — só se via o que já era nosso — mas
        fazia o projeto deixar de querer dizer alguma coisa. E ficou pior
        quando a app passou a abrir nas Descobertas: abre-se um projeto vazio
        e ele mostra trabalho de outro.

        `space_id` opcional para não partir quem chama sem ele (a web, e o
        feed global). Quem o manda, fica com o feed do projeto.
        """
        space_strs = [str(s) for s in space_ids]  # Agent.scope_id is text
        crew_strs = [str(c) for c in crew_ids]

        clauses = []
        if space_ids:
            clauses.append(
                and_(
                    AgentFinding.source == "scan",
                    AgentFinding.space_id.in_(space_ids),
                )
            )
        # Filtrado por projeto: só o que é DELE.
        #
        # Um agente pertence a um projeto pelo `scope`/`scope_id` — de espaço
        # directamente, de crew através da crew. O "sou eu o dono" desaparece
        # aqui de propósito: dentro de um projeto, ser meu não chega para o
        # achado ser deste sítio.
        if space_id is not None:
            # `Agent.scope_id` é TEXTO — a coluna guarda o id do espaço ou da
            # crew conforme o `scope`. Daí o `cast`: comparar texto com uuid
            # não dá erro no Postgres, dá zero resultados, que é pior.
            crews_do_projeto = select(cast(Crew.id, String)).where(Crew.space_id == space_id)
            return or_(
                and_(
                    AgentFinding.source == "scan",
                    AgentFinding.space_id == space_id,
                ),
                and_(
                    AgentFinding.agent_id.isnot(None),
                    or_(
                        and_(Agent.scope == "space", Agent.scope_id == str(space_id)),
                        and_(Agent.scope == "crew", Agent.scope_id.in_(crews_do_projeto)),
                    ),
                ),
            )

        agent_clauses = [Agent.created_by == user_id]
        if space_strs:
            agent_clauses.append(and_(Agent.scope == "space", Agent.scope_id.in_(space_strs)))
        if crew_strs:
            agent_clauses.append(and_(Agent.scope == "crew", Agent.scope_id.in_(crew_strs)))
        clauses.append(and_(AgentFinding.agent_id.isnot(None), or_(*agent_clauses)))
        return or_(*clauses)

    @staticmethod
    def _aplicar_busca(query, q: Optional[str]):
        """Procurar nos MESMOS campos em que a web procura.

        A app procurava só no `title`, e só no que já estava carregado — 20
        achados de cada vez. Escrever uma palavra que está no achado 25 não
        dava nada, e lia-se como «não existe».

        A web procura em cinco campos, do lado dela, sobre tudo o que tinha
        carregado. Passar isto para o servidor resolve as duas coisas ao mesmo
        tempo: procura em tudo o que existe, e os dois clientes passam a
        encontrar o mesmo com a mesma palavra.

        `agent_name` está na tabela dos achados só para os de varredura; o
        nome do agente a sério vem do `Agent`, e os dois entram.
        """
        alvo = (q or "").strip()
        if not alvo:
            return query
        # `ilike` e não `to_tsvector`: isto é uma caixa de busca sobre umas
        # centenas de linhas por cliente, não um motor de pesquisa. Sem
        # acentuação e sem radicais é o que a web já faz, e por isso é o que
        # devolve os mesmos resultados.
        padrao = f"%{alvo}%"
        return query.where(
            or_(
                AgentFinding.title.ilike(padrao),
                AgentFinding.description.ilike(padrao),
                AgentFinding.recommendation.ilike(padrao),
                AgentFinding.agent_name.ilike(padrao),
                Agent.name.ilike(padrao),
            )
        )

    def _base_query(self, user_id: UUID):
        return (
            select(AgentFinding, Agent, InsightState)
            .select_from(AgentFinding)
            .outerjoin(Agent, AgentFinding.agent_id == Agent.id)
            .outerjoin(
                InsightState,
                and_(
                    InsightState.finding_id == AgentFinding.id,
                    InsightState.user_id == user_id,
                ),
            )
        )

    @staticmethod
    def _apply_filter(query, filter_: str):
        # Os TIPOS de achado — os mesmos três que a web oferece.
        if filter_ in ("risk", "opportunity", "insight"):
            return query.where(AgentFinding.type == filter_)

        # O ESTADO, por pessoa. «Novo» quer dizer novo para quem está a ver, e
        # é isso que o torna útil — o `InsightState` é por utilizador.
        if filter_ == "new":
            return query.where(InsightState.reviewed_at.is_(None))
        if filter_ == "reviewed":
            return query.where(InsightState.reviewed_at.isnot(None))
        if filter_ == "pinned":
            return query.where(InsightState.pinned_at.isnot(None))

        if filter_ == "featured":
            return query.where(
                or_(InsightState.pinned_at.isnot(None), AgentFinding.severity == "high")
            )

        # `latest` cai aqui com `all` — e sempre caiu. É a mesma consulta e a
        # mesma contagem; a app tinha uma pastilha «Recentes» que não fazia
        # rigorosamente nada, e já saiu de lá.
        return query

    # ─── Feed ────────────────────────────────────────────────────────────

    async def list(
        self,
        user_id: UUID,
        filter_: str,
        cursor: Optional[str],
        limit: int,
        space_id: Optional[UUID] = None,
        q: Optional[str] = None,
    ) -> InsightFeedResponse:
        space_ids, crew_ids = await self._member_scope(user_id)
        scope = self._scope_where(user_id, space_ids, crew_ids, space_id)

        query = self._base_query(user_id).where(scope).where(AgentFinding.dismissed.is_(False))
        query = self._apply_filter(query, filter_)
        query = self._aplicar_busca(query, q)

        if cursor:
            c_created, c_id = self._decode_cursor(cursor)
            query = query.where(
                or_(
                    AgentFinding.created_at < c_created,
                    and_(
                        AgentFinding.created_at == c_created,
                        AgentFinding.id < c_id,
                    ),
                )
            )

        query = query.order_by(AgentFinding.created_at.desc(), AgentFinding.id.desc()).limit(
            limit + 1
        )

        rows = (await self.db.execute(query)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [self._to_item(f, a, s) for (f, a, s) in rows]
        next_cursor = self._encode_cursor(rows[-1][0]) if has_more and rows else None
        # As contagens seguem o mesmo âmbito da lista: senão a pastilha
        # «Todos 12» ficava por cima de uma lista de três.
        counts = await self._counts(user_id, space_ids, crew_ids, space_id)
        return InsightFeedResponse(items=items, next_cursor=next_cursor, counts=counts)

    async def _counts(
        self,
        user_id: UUID,
        space_ids: List[UUID],
        crew_ids: List[UUID],
        space_id: Optional[UUID] = None,
    ) -> Dict[str, int]:
        scope = self._scope_where(user_id, space_ids, crew_ids, space_id)
        by_type_rows = (
            await self.db.execute(
                select(AgentFinding.type, func.count())
                .select_from(AgentFinding)
                .outerjoin(Agent, AgentFinding.agent_id == Agent.id)
                .where(scope)
                .where(AgentFinding.dismissed.is_(False))
                .group_by(AgentFinding.type)
            )
        ).all()
        by_type = {t: c for (t, c) in by_type_rows}

        featured = (
            await self.db.execute(
                select(func.count())
                .select_from(AgentFinding)
                .outerjoin(Agent, AgentFinding.agent_id == Agent.id)
                .outerjoin(
                    InsightState,
                    and_(
                        InsightState.finding_id == AgentFinding.id,
                        InsightState.user_id == user_id,
                    ),
                )
                .where(scope)
                .where(AgentFinding.dismissed.is_(False))
                .where(
                    or_(
                        InsightState.pinned_at.isnot(None),
                        AgentFinding.severity == "high",
                    )
                )
            )
        ).scalar() or 0

        # O ESTADO, por pessoa. Faltava: as pastilhas Novo / Vistos /
        # Fixados existiam e não tinham número, e uma pastilha sem número ao
        # lado de outras com número lê-se como «zero».
        #
        # Uma consulta só, agrupada por «tem data de revisão ou não» — três
        # consultas separadas para responder à mesma pergunta seriam três
        # viagens para o mesmo sítio.
        por_estado = (
            await self.db.execute(
                select(
                    InsightState.reviewed_at.isnot(None).label("visto"),
                    func.count(),
                )
                .select_from(AgentFinding)
                .outerjoin(Agent, AgentFinding.agent_id == Agent.id)
                .outerjoin(
                    InsightState,
                    and_(
                        InsightState.finding_id == AgentFinding.id,
                        InsightState.user_id == user_id,
                    ),
                )
                .where(scope)
                .where(AgentFinding.dismissed.is_(False))
                .group_by(InsightState.reviewed_at.isnot(None))
            )
        ).all()
        vistos = sum(c for (visto, c) in por_estado if visto)
        novos = sum(c for (visto, c) in por_estado if not visto)

        fixados = (
            await self.db.execute(
                select(func.count())
                .select_from(AgentFinding)
                .outerjoin(Agent, AgentFinding.agent_id == Agent.id)
                .outerjoin(
                    InsightState,
                    and_(
                        InsightState.finding_id == AgentFinding.id,
                        InsightState.user_id == user_id,
                    ),
                )
                .where(scope)
                .where(AgentFinding.dismissed.is_(False))
                .where(InsightState.pinned_at.isnot(None))
            )
        ).scalar() or 0

        total = sum(by_type.values())
        return {
            "all": total,
            "latest": total,
            "risk": by_type.get("risk", 0),
            "opportunity": by_type.get("opportunity", 0),
            "insight": by_type.get("insight", 0),
            "featured": int(featured),
            "new": int(novos),
            "reviewed": int(vistos),
            "pinned": int(fixados),
        }

    # ─── Detail ──────────────────────────────────────────────────────────

    async def detail(self, user_id: UUID, finding_id: str) -> Optional[InsightDetail]:
        row = await self._scoped_row(user_id, finding_id)
        if row is None:
            return None
        f, a, s = row
        base = self._to_item(f, a, s).model_dump()
        return InsightDetail(
            **base,
            description=f.description or "",
            stat_tiles=list(f.stat_tiles or []),
            viz_kind=f.viz_kind,
        )

    async def _scoped_row(self, user_id: UUID, finding_id: str):
        """The (finding, agent, state) tuple for ``finding_id`` IF it is in the
        caller's scope — else ``None`` (which the endpoint turns into 404, never
        a 403 that would leak the finding's existence)."""
        try:
            fid = UUID(str(finding_id))
        except (ValueError, TypeError):
            return None
        space_ids, crew_ids = await self._member_scope(user_id)
        # SEM projeto, de propósito: abrir UM achado é o que uma notificação
        # ou uma ligação directa fazem, e essas chegam de fora sem projeto
        # escolhido. Filtrar aqui fazia uma notificação deixar de abrir por a
        # pessoa estar «noutro sítio» — que é uma ideia da interface, não do
        # achado. O que se pode ver continua a ser o mesmo.
        scope = self._scope_where(user_id, space_ids, crew_ids)
        query = self._base_query(user_id).where(scope).where(AgentFinding.id == fid)
        return (await self.db.execute(query)).first()

    # ─── Review / pin (per-user, idempotent) ─────────────────────────────

    async def reclassificar(
        self,
        user_id: UUID,
        finding_id: str,
        tipo: Optional[str],
        gravidade: Optional[str],
    ) -> bool:
        """Corrige a classificação de um achado.

        A Sky classifica ao gravar; isto é a correcção de quem discorda, e vale
        mais do que a adivinhação inicial — quem está a ver o achado sabe se
        aquilo é mesmo um risco.

        **Não é por pessoa**, ao contrário do «visto» e do «fixado»: a
        classificação é do achado e muda para toda a gente. Um risco não é
        risco só para mim.

        Passa pelo mesmo `_scoped_row` de sempre: só se corrige o que já se
        podia ver. Devolve `False` quando não há achado — e é o mesmo `False`
        de «não existe» e de «não é para si», de propósito, para não confirmar
        a existência de um achado a quem não lhe chega.
        """
        from src.models.agent import AgentFinding as _AF

        linha = await self._scoped_row(user_id, finding_id)
        if linha is None:
            return False

        # Valores fora da lista não se gravam. Um `type` inventado deixa o
        # achado fora de todos os filtros — invisível sem estar apagado, que é
        # a pior maneira de perder uma coisa.
        if tipo is not None and tipo not in ("risk", "opportunity", "insight"):
            return False
        if gravidade is not None and gravidade not in ("high", "med", "low"):
            return False

        achado: _AF = linha[0]
        if tipo is not None:
            achado.type = tipo
        if gravidade is not None:
            achado.severity = gravidade
        await self.db.flush()
        return True

    async def set_reviewed(self, user_id: UUID, finding_id: str, reviewed: bool) -> bool:
        return await self._set_flag(user_id, finding_id, "reviewed_at", reviewed)

    async def set_pinned(self, user_id: UUID, finding_id: str, pinned: bool) -> bool:
        return await self._set_flag(user_id, finding_id, "pinned_at", pinned)

    async def _set_flag(self, user_id: UUID, finding_id: str, column: str, value: bool) -> bool:
        row = await self._scoped_row(user_id, finding_id)
        if row is None:
            return False  # not in scope → endpoint returns 404
        finding = row[0]
        state = (
            await self.db.execute(
                select(InsightState)
                .where(InsightState.user_id == user_id)
                .where(InsightState.finding_id == finding.id)
            )
        ).scalar_one_or_none()
        if state is None:
            state = InsightState(user_id=user_id, finding_id=finding.id)
            self.db.add(state)
        setattr(state, column, datetime.now(timezone.utc) if value else None)
        state.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    # ─── Mapping helpers ─────────────────────────────────────────────────

    def _to_item(self, f: AgentFinding, agent, state) -> InsightItem:
        return InsightItem(
            id=str(f.id),
            severity=f.type,
            severity_level=f.severity,
            agent_name=f.agent_name or (agent.name if agent is not None else None),
            title=f.title,
            summary=(f.description or "")[:400],
            is_live=self._is_live(f, agent),
            series=list(f.series or []),
            created_at=f.created_at,
            reviewed=bool(state is not None and state.reviewed_at is not None),
            pinned=bool(state is not None and state.pinned_at is not None),
            deep_link=f"sky://insights/{f.id}",
            # O fio onde este achado foi publicado. Tocar no insight abre a
            # conversa do agente, e nao uma pagina sem saida.
            conversation_id=(
                str(agent.conversation_id)
                if agent is not None and agent.conversation_id
                else None
            ),
        )

    @staticmethod
    def _aware(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def _is_live(self, f: AgentFinding, agent) -> bool:
        now = datetime.now(timezone.utc)
        if f.source == "scan":
            created = self._aware(f.created_at)
            return created is not None and (now - created) < _SCAN_LIVE_WINDOW
        if agent is not None and agent.status == "active":
            last = self._aware(agent.last_execution_at)
            return last is not None and (now - last) < _AGENT_LIVE_WINDOW
        return False

    # ─── Cursor (keyset on created_at, id) ───────────────────────────────

    @staticmethod
    def _encode_cursor(finding: AgentFinding) -> str:
        payload = json.dumps([finding.created_at.isoformat(), str(finding.id)])
        return base64.urlsafe_b64encode(payload.encode()).decode()

    @staticmethod
    def _decode_cursor(cursor: str) -> Tuple[datetime, UUID]:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode()).decode()
            created_iso, id_str = json.loads(raw)
            return datetime.fromisoformat(created_iso), UUID(id_str)
        except Exception as exc:  # noqa: BLE001 — any malformed input → 400
            raise InvalidCursor(str(exc)) from exc
