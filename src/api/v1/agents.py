"""Agent API endpoints — CRUD, pause/resume, findings, run (worker)."""

import json
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.locale import get_message, lingua_da_resposta
from src.models.agent import Agent
from src.models.user import User

logger = logging.getLogger(__name__)


from src.schemas.agent import (
    AddFindingToPageRequest,
    AddFindingToPageResponse,
    AgentCreate,
    AgentFindingResponse,
    AgentListResponse,
    AgentResponse,
    AgentUpdate,
)
from src.schemas.chat_stream import SSE_HEADERS
from src.services import pricing_service
from src.services.agent_service import AgentService
from src.services.rbac_service import RBACService
from src.core.permissions import TENANT_ADMIN_ROLES

router = APIRouter()


async def get_agent_service(db: AsyncSession = Depends(get_db_session)) -> AgentService:
    return AgentService(db)


async def _assert_can_act_on_agent_scope(
    db: AsyncSession,
    user: User,
    *,
    scope: Optional[str],
    scope_id: Optional[str],
    permission: str,
) -> None:
    """RBAC for an agent action that may live in any scope.

    Personal agents are owned-by-creator: ``scope == "personal"`` and
    ``scope_id`` is the creator's user UUID. The Space-scoped permissions
    catalog doesn't apply to them — only the owner (and platform Owner /
    Admin) can act. This mirrors ``AgentService._require_can_mutate`` so
    the route-level gate doesn't 403 a user who would otherwise be
    allowed by the service-layer guard.

    For ``space`` (and crew/org via space_id resolution), the standard
    RBAC catalog applies — e.g. ``agents.create`` requires editor on the
    target Space.
    """
    scope_lower = (scope or "").lower()

    if scope_lower == "personal":
        platform = (user.role or "").lower()
        if platform in TENANT_ADMIN_ROLES:
            return
        try:
            owner_id = UUID(str(scope_id))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid personal-scope agent identity",
            )
        if owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Personal agents are owned by their creator",
            )
        return

    s_id: Optional[UUID] = None
    c_id: Optional[UUID] = None
    if scope_lower == "space" and scope_id:
        try:
            s_id = UUID(scope_id)
        except ValueError:
            pass
    elif scope_lower == "crew" and scope_id:
        # O âmbito de equipa não estava a ser passado ao RBAC.
        #
        # Ficava `space_id=None` e `crew_id=None`, e a verificação caía no papel
        # genérico da pessoa no cliente — que qualquer membro tem. Quem não
        # pertencesse à equipa passava na mesma.
        #
        # Isso importava porque, a seguir, o `resolved_crew_ids` é
        # `[agent.scope_id]`: a equipa DO AGENTE, não as de quem o corre. As
        # tabelas autorizadas saíam dessa equipa, e a resposta vinha com dados
        # que a pessoa não devia ver. O `get_agent` também não filtra
        # visibilidade — devolve qualquer agente por id —, portanto o único
        # obstáculo era saber o UUID, e um UUID não é um controlo de acesso.
        #
        # Com o `crew_id` passado, o RBAC resolve o papel na equipa e devolve
        # `no_access` a quem não é membro.
        try:
            c_id = UUID(scope_id)
        except ValueError:
            pass
    await RBACService(db).assert_permission(user, permission, space_id=s_id, crew_id=c_id)


async def _is_content_member(db: AsyncSession, user: User, scope, scope_id) -> bool:
    """Option B: is ``user`` a real member entitled to an agent's CONTENT
    (findings/insights)? No platform-role bypass. crew → crew membership;
    space → space or any-crew-in-space membership; personal → the creator.
    """
    sc = (scope or "").lower()
    if not scope_id:
        return sc == "personal"  # malformed scoped agent — treat as private
    from src.services.authorization import Authorization

    authz = Authorization(db)
    try:
        sid = UUID(str(scope_id))
    except (ValueError, TypeError):
        return False
    if sc == "crew":
        return await authz.get_crew_role(user.id, sid) is not None
    if sc == "space":
        if await authz.get_space_role(user.id, sid) is not None:
            return True
        return await authz.get_best_crew_role_in_space(user.id, sid) is not None
    # personal / organization — handled by the caller (creator check).
    return False


@router.get("/", response_model=List[AgentListResponse])
async def list_agents(
    scope: Optional[str] = Query(
        None, description="Filter by scope: personal, space, crew, organization"
    ),
    scope_id: Optional[str] = Query(None, description="Filter by scope entity ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """List agents. Filter by scope/scope_id or get all accessible agents."""
    # Scoped listings (scope=personal|space|crew|...) walk the unified
    # RBAC helper — personal is owner-by-creator, space goes through the
    # standard catalog. An unscoped listing is owner-or-admin only:
    # platform Owner/Admin see everything, Members get auto-narrowed to
    # their own personal agents below (so the unfiltered created_by=None
    # path doesn't leak).
    if scope:
        await _assert_can_act_on_agent_scope(
            db,
            current_user,
            scope=scope,
            scope_id=scope_id,
            permission="agents.view",
        )

    # SECURITY: when the caller doesn't pin a scope, default to their
    # own personal agents (created_by=current_user.id) instead of
    # returning every agent in the tenant. Previously the unfiltered
    # `created_by=None` path leaked cross-user personal agents
    # ("Monitor: AI Response..." etc. from other users) to anyone
    # with agents.view. Org admins/owners can still see the full
    # list — they bypass at assert_permission, so we keep the
    # unfiltered path for them. Scoped requests (space / crew) keep
    # the existing access-checked behaviour because the scope filter
    # itself constrains the visibility set.
    is_org_admin = (current_user.role or "").lower() in TENANT_ADMIN_ROLES
    if not scope and not is_org_admin:
        return await service.list_agents(scope=None, scope_id=None, created_by=current_user.id)
    return await service.list_agents(scope=scope, scope_id=scope_id, created_by=None)


@router.post("/", response_model=AgentListResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    data: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """Create a new agent.

    Personal-scope agents are explicitly allowed: they are owned by
    their creator (scope_id == user.id) and walk the same FE wizard as
    Space agents. ``_assert_can_act_on_agent_scope`` enforces the
    "owner-or-platform-admin" rule for personal scope and the standard
    Space-RBAC for collaborative scopes.

    For personal scope, the route used to compare the posted scope_id
    to the caller's id and 403 on mismatch — but the FE wizard in modo
    PERSONAL frequently posts an empty / placeholder value, which
    blocked users from ever creating a personal agent. The route now
    short-circuits the RBAC check for personal scope (it implicitly
    targets the current user) and the service normalises scope_id
    back to user.id before the row is written.
    """
    scope_str = (
        data.scope.value if hasattr(data.scope, "value") else str(data.scope or "")
    ).lower()

    # Space→Crew security boundary (2026-06): agents are ALWAYS created at
    # the crew level, never on a bare space. A space-scoped agent would run
    # over the union of the space's crews' tables; the new model requires an
    # explicit crew so its data surface is the one the operator granted.
    # Personal / crew / organization scopes are still allowed. Gated by the
    # same flag as the query guard so FE + BE roll out together.
    from src.config.settings import settings as _crew_settings

    if _crew_settings.CREW_REQUIRED_FOR_QUERY and scope_str == "space":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Agents must be created at the crew level, not the space level. "
                "Select a crew — every space has a default 'General' crew."
            ),
        )

    if scope_str != "personal":
        if not data.scope_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"scope_id is required when scope={scope_str!r}",
            )
        await _assert_can_act_on_agent_scope(
            db,
            current_user,
            scope=data.scope,
            scope_id=data.scope_id,
            permission="agents.create",
        )

    # Demo guard: limit how many agents each user can create so token
    # consumption stays bounded. Platform owners/admins are exempt.
    from src.config.settings import settings as _settings

    _max = _settings.DEMO_MAX_AGENTS_PER_USER if _settings.DEMO_ENABLED else 0
    _role = (current_user.role or "").lower()
    if _max > 0 and _role not in TENANT_ADMIN_ROLES:
        _count_result = await db.execute(
            select(func.count())
            .select_from(Agent)
            .where(
                Agent.created_by == current_user.id,
            )
        )
        _count = _count_result.scalar() or 0
        if _count >= _max:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Agent limit reached. Demo accounts can have up to {_max} agents. "
                    "Delete an existing agent to create a new one."
                ),
            )

    # Pricing Fase 1 — tier enforcement. Raises TierLimitExceededError
    # (HTTP 402) BEFORE the agent row is created so we don't have to
    # clean up on the way out. The counter bump happens after the
    # service confirms the insert; if anything between here and the
    # bump fails, the row is gone (transaction rollback) and the
    # counter stays consistent.
    # O limite do plano é verificado dentro do serviço (limites_do_plano).
    agent = await service.create_agent(data, user_id=current_user.id)

    # ── A PRIMEIRA CORRIDA É AGORA ───────────────────────────────────────
    #
    # Criar um agente guardava-o e ia-se embora à espera do agendador. Quem o
    # acabou de criar ficava a olhar para um ecrã onde não acontecia nada; o
    # primeiro achado chegava no dia seguinte, se a pessoa se lembrasse de
    # voltar.
    #
    # Esse é o único momento em que alguém está a olhar à espera de prova — e
    # era gasto a não acontecer nada. É a diferença entre «fiz um agente» e «a
    # Sky encontrou-me isto».
    #
    # **Falhar aqui NÃO desfaz a criação.** O agente existe e vai correr na
    # cadência dele; só a estreia é que se perdeu. Devolver 503 e deixar o
    # cliente a pensar que não criou nada seria trocar um atraso por uma
    # mentira. Fica no registo, e o ecrã tem o «Perguntar agora».
    try:
        from src.workers.agent_worker import execute_agent

        execute_agent.delay(str(agent.id))
        # O `/run` que a app chama logo a seguir não a repete — ver
        # `services/estreia_do_agente.py`.
        from src.services import estreia_do_agente

        await estreia_do_agente.marcar(agent.id)
    except Exception as e:
        logging.getLogger(__name__).error(
            f"Agent {agent.id} created but the first run could not be queued: {e}",
            exc_info=True,
        )

    # E o FIO tambem nasce agora.
    #
    # A conversa do agente so nascia dentro do worker, ao gravar o primeiro
    # achado. Um agente que ainda nao encontrou nada nao tinha fio nenhum — e
    # a lista mostrava «Abrir conversa» num agente e em mais nenhum, o que o
    # Lucas leu como «tem aqui um agente diferente dos outros».
    #
    # Nao ha agentes diferentes. Ha agentes que ja falaram e agentes que
    # ainda nao, e os dois tem onde falar.
    try:
        from src.services.agent_conversation_service import ensure_agent_conversation

        await ensure_agent_conversation(db, agent)
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "Agent %s created but its conversation could not be opened: %s",
            agent.id,
            e,
        )

    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """Get agent detail. Findings (content) are included only for members."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=agent.scope,
        scope_id=agent.scope_id,
        permission="agents.view",
    )
    # Option B (2026-06): findings are CONTENT. The scope check above lets a
    # platform admin SEE the agent (management plane), but its insights
    # require real membership — strip findings for non-members so an admin
    # who was not added to the crew sees the agent exists, not its insights.
    sc = (agent.scope or "").lower()
    if sc in ("personal", "organization"):
        is_member = agent.created_by == current_user.id
    else:
        is_member = await _is_content_member(db, current_user, agent.scope, agent.scope_id)
    if not is_member:
        agent.findings = []
        # Transient flag read by AgentResponse (from_attributes) so the UI can
        # show an "ask to be added" mask rather than an empty insights tab.
        agent.findings_restricted = True
    return agent


@router.put("/{agent_id}", response_model=AgentListResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """Update agent configuration."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=agent.scope,
        scope_id=agent.scope_id,
        permission="agents.edit",
    )
    return await service.update_agent(agent_id, data, current_user)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """Delete an agent and all its findings."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.delete",
    )
    await service.delete_agent(agent_id, current_user)
    # Release the tier slot — mirror of record_agent_created in POST /. The
    # counter is decremented only after the delete commits; _bump_counter
    # clamps at 0 so this can never underflow.
    await pricing_service.record_agent_deleted(db)
    return None


@router.post("/{agent_id}/pause", response_model=AgentListResponse)
async def pause_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """Pause an active agent."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.pause",
    )
    return await service.pause_agent(agent_id)


@router.post("/{agent_id}/resume", response_model=AgentListResponse)
async def resume_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """Resume a paused agent."""
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.resume",
    )
    return await service.resume_agent(agent_id)


@router.post("/{agent_id}/run")
async def run_agent_now(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Trigger an immediate execution of the agent."""
    import logging

    from sqlalchemy import select

    from src.models.agent import Agent

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Agent not found")

    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.run",
    )

    # SEM PERGUNTAS NO MÊS, diz-se JÁ — com o 402 e a frase do plano.
    #
    # Uma corrida pedida gasta uma pergunta como outra qualquer. Sem esta
    # verificação, o botão respondia 200, levava ao fio, e a corrida saltava
    # lá dentro: quem carregou ficava a ver a barra «a trabalhar» até
    # desistir. O worker volta a verificar (o saldo pode acabar entretanto).
    from src.services import limites_do_plano

    await limites_do_plano.verificar_saldo()

    # A estreia de um agente acabado de criar já está na fila (o `POST
    # /agents/` pô-la lá). A app chamava `/run` a seguir e o agente corria
    # DUAS vezes — duas perguntas do plano. O primeiro `/run` depois da
    # criação consome a marca e não repete; os seguintes correm.
    from src.services import estreia_do_agente

    already_queued = await estreia_do_agente.ja_esta_na_fila(agent_id)

    # Uma falha a pôr na fila é uma FALHA, e diz-se.
    #
    # Isto engolia a excepção e respondia 200 na mesma. Com o worker em baixo,
    # a app dizia «está a correr, o que encontrar aparece nos Insights» — e não
    # corria nada. Ninguém ficava a saber: nem quem carregou, nem quem estava a
    # ver o ecrã à espera.
    #
    # Um botão que finge é pior do que um botão a menos.
    try:
        from src.workers.agent_worker import execute_agent

        # `a_pedido`: alguem carregou no botao. Um agente em pausa obedece a
        # um pedido directo — «em pausa» quer dizer «nao vas ver por tua
        # conta», nao «recusa-te quando eu te pergunto».
        if not already_queued:
            execute_agent.delay(str(agent_id), a_pedido=True)
    except Exception as e:
        logging.getLogger(__name__).error(f"Could not enqueue agent task: {e}", exc_info=True)
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail="Could not start the agent right now. Nothing was lost — try again in a moment.",
        )

    # A conversa do agente, ABERTA JA — e nao so quando ele encontrar alguma
    # coisa.
    #
    # O Lucas carregou em «Perguntar agora» e apanhou um aviso: «corre em
    # segundo plano, o que encontrar aparece nas Descobertas». Nao e o que ele
    # quer nem o que ficou decidido a 22/08: **a descoberta e a casa, e cada
    # corrida e uma mensagem no fio do agente.** Carregar tem de LEVAR ao fio.
    #
    # Nao havia para onde levar. A conversa so nascia dentro do worker, ao
    # gravar o primeiro achado — portanto um agente que nunca encontrou nada
    # nao tinha fio, e a lista mostrava «Abrir conversa» num agente e em mais
    # nenhum. Ele reparou: «parece que tem um agente diferente dos outros».
    #
    # Falhar aqui nao pode impedir a corrida, que ja esta na fila.
    conversa = getattr(agent, "conversation_id", None)
    try:
        from src.services.agent_conversation_service import ensure_agent_conversation

        conversa = await ensure_agent_conversation(db, agent) or conversa
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("Could not open the agent's conversation: %s", e)

    return {
        "message": "Agent execution started",
        "agent_id": str(agent_id),
        # Para onde a app deve levar quem carregou. `None` quando nao ha
        # pagina onde por a conversa — nesse caso a app fica onde esta.
        "conversation_id": str(conversa) if conversa else None,
        # True quando esta chamada NÃO pôs nada na fila porque a estreia (da
        # criação) já lá estava. Para a app é igual: o agente está a correr.
        "already_queued": already_queued,
    }


@router.post("/{agent_id}/run/stream")
async def run_agent_stream(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """«Executar agora» da web antiga — agora PELO MESMO CAMINHO do `/run`.

    Esta rota corria o agente dentro da API, com um caminho próprio que tinha
    ficado para trás de tudo o que o worker passou a fazer: não gastava
    pergunta do plano (`verificar_saldo` / `reservar_pergunta`), não
    reverificava o acesso do dono às fontes (#745), não aplicava o recorte por
    equipa nem o modo «contexto» de análise do negócio (#746), não escrevia a
    corrida como mensagem no fio do agente e não actualizava
    `execution.answer` / `last_answer`. E dava 400 «Agent has no connections
    to analyze» a todos os agentes criados na app (`connection_ids=[]`).

    Agora faz exactamente o que o `/run` faz — as mesmas verificações, a mesma
    tarefa na fila — e devolve o resultado em SSE para a web antiga não
    rebentar enquanto não passa para o `/run`: um `progress`, um `chunk` com a
    frase de onde vai aparecer a resposta, e um `done` com o
    `conversation_id`. Recusas (402 sem perguntas, 403 sem permissão, 404,
    503 sem worker) saem como HTTP, antes do stream, como no `/run`.

    A app móvel nunca usou esta rota (só `/run`).
    """
    corrida = await run_agent_now(agent_id=agent_id, current_user=current_user, db=db)
    locale = lingua_da_resposta(getattr(current_user, "preferences", None))
    frase = get_message("agent_run_queued", locale)

    async def eventos():
        yield f"data: {json.dumps({'type': 'progress', 'stage': 'starting', 'message': frase})}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': frase})}\n\n"
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "done",
                    "queued": True,
                    "agent_id": corrida.get("agent_id"),
                    "conversation_id": corrida.get("conversation_id"),
                }
            )
            + "\n\n"
        )

    return StreamingResponse(
        eventos(),
        media_type="text/event-stream",
        headers={
            **SSE_HEADERS,
            "Deprecation": "true",
            "Link": f'</api/v1/agents/{agent_id}/run>; rel="successor-version"',
        },
    )


# ─── Findings ───


@router.get("/insights/all", response_model=List[AgentFindingResponse])
async def list_all_insights(
    scope: Optional[str] = Query(None),
    scope_id: Optional[str] = Query(None),
    include_dismissed: bool = Query(False),
    limit: int = Query(50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """List all insights across all agents, optionally filtered by scope.

    SECURITY (audit 2026-05-05): without a scope filter the previous
    implementation returned findings from every Agent in the tenant
    to any caller with global ``agents.findings.view``. Now: when the
    caller is not an org admin/owner AND no explicit scope is pinned,
    we restrict the agent list to ones they own or are members of.
    """
    await RBACService(db).assert_permission(current_user, "agents.findings.view")
    from sqlalchemy.orm import selectinload

    query = select(Agent)
    # ── «Este projecto» inclui as equipas de dentro ──────────────────
    #
    # > «porque o Hallazgos aparece Todo en orden? cade eles?»
    # > — Lucas, 07/10/2026
    #
    # Havia 18 descobertas na base, nenhuma descartada, todas de agentes
    # dele e de equipas dele. O ecrã dizia que estava tudo em ordem.
    #
    # Isto era `Agent.scope == scope`, e um agente nasce sempre ao nível
    # da EQUIPA (`scope="crew"`): dos 21, 18 eram de equipa e nenhum
    # passava o filtro `scope="space"`.
    #
    # A regra certa já existia — no `AgentRepository.list_all`, que é o
    # que serve a LISTA de agentes, e foi escrita para este mesmo
    # defeito em Junho. A lista mostrava os agentes e as descobertas
    # deles ficavam escondidas, porque cada endpoint tinha a sua cópia
    # da pergunta «de quem é este agente». Agora é uma só.
    projeto: Optional[UUID] = None
    if (scope or "").lower() == "space" and scope_id:
        try:
            projeto = UUID(str(scope_id))
        except (ValueError, AttributeError, TypeError):
            # Um identificador mal formado dá lista vazia, e não um 500.
            projeto = None
    if projeto is not None:
        from src.repositories.agent import agentes_do_projeto

        query = query.where(agentes_do_projeto(projeto))
    else:
        if scope:
            query = query.where(Agent.scope == scope)
        if scope_id:
            query = query.where(Agent.scope_id == scope_id)

    # Option B (2026-06): agent findings are CONTENT — even org admins only
    # see findings from agents they own or whose Space/Crew they belong to
    # (no platform-role bypass). A crew member sees their crew-agents'
    # findings; a non-member admin sees a count via the agents list but NOT
    # the insights here.
    from sqlalchemy import and_, or_

    from src.models.crew import CrewMember
    from src.models.space import SpaceMember

    member_space_ids = [
        str(sid)
        for sid in (
            await db.execute(
                select(SpaceMember.space_id).where(SpaceMember.user_id == current_user.id)
            )
        )
        .scalars()
        .all()
    ]
    member_crew_ids = [
        str(cid)
        for cid in (
            await db.execute(
                select(CrewMember.crew_id).where(CrewMember.user_id == current_user.id)
            )
        )
        .scalars()
        .all()
    ]
    clauses = [Agent.created_by == current_user.id]
    if member_space_ids:
        clauses.append(and_(Agent.scope == "space", Agent.scope_id.in_(member_space_ids)))
    if member_crew_ids:
        clauses.append(and_(Agent.scope == "crew", Agent.scope_id.in_(member_crew_ids)))
    query = query.where(or_(*clauses))

    result = await db.execute(query.options(selectinload(Agent.findings)))
    agents = result.scalars().all()

    # Keep the finding paired with its agent so we can stamp the origin
    # (agent name + scope + space/page) onto each response below. The global
    # Pulse feed needs this to badge "space › crew › page" and deep-link.
    pairs: list = []
    for agent in agents:
        for f in agent.findings or []:
            if not include_dismissed and f.dismissed:
                continue
            pairs.append((f, agent))

    pairs.sort(key=lambda p: p[0].created_at or "", reverse=True)
    pairs = pairs[:limit]

    # Batch-resolve crew → space and page names for just the limited set
    # (one extra query each, only when there's something to resolve).
    from src.models.crew import Crew
    from src.models.page import Page
    from src.models.space import Space

    crew_ids = {
        str(a.scope_id) for _, a in pairs if (a.scope or "").lower() == "crew" and a.scope_id
    }
    page_ids = {str(f.added_to_page_id) for f, _ in pairs if f.added_to_page_id}

    crew_to_space: dict[str, tuple[Optional[str], Optional[str]]] = {}
    if crew_ids:
        rows = (
            await db.execute(
                select(Crew.id, Crew.space_id, Space.name)
                .join(Space, Space.id == Crew.space_id, isouter=True)
                .where(Crew.id.in_([UUID(c) for c in crew_ids]))
            )
        ).all()
        for cid, sid, sname in rows:
            crew_to_space[str(cid)] = (str(sid) if sid else None, sname)

    page_names: dict[str, str] = {}
    if page_ids:
        rows = (
            await db.execute(
                select(Page.id, Page.name).where(Page.id.in_([UUID(p) for p in page_ids]))
            )
        ).all()
        page_names = {str(pid): pname for pid, pname in rows}

    responses: list[AgentFindingResponse] = []
    for f, agent in pairs:
        resp = AgentFindingResponse.model_validate(f)
        scope_lower = (agent.scope or "").lower()
        resp.agent_name = agent.name
        resp.scope = agent.scope
        resp.scope_id = str(agent.scope_id) if agent.scope_id else None
        resp.scope_name = agent.scope_name
        if scope_lower == "crew" and agent.scope_id:
            sid, sname = crew_to_space.get(str(agent.scope_id), (None, None))
            resp.space_id = sid
            resp.space_name = sname
        elif scope_lower == "space" and agent.scope_id:
            resp.space_id = str(agent.scope_id)
            resp.space_name = agent.scope_name
        if f.added_to_page_id:
            resp.page_id = f.added_to_page_id
            resp.page_name = page_names.get(str(f.added_to_page_id))
        responses.append(resp)

    return responses


@router.get("/{agent_id}/findings", response_model=List[AgentFindingResponse])
async def list_findings(
    agent_id: UUID,
    include_dismissed: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """List findings for an agent."""
    await RBACService(db).assert_permission(current_user, "agents.findings.view")
    # Content gate (Option B): a crew/space-scoped agent's findings require
    # membership of that crew/space — no platform-role bypass. Personal
    # agents: only the creator.
    agent_row = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent_row is not None:
        scope_str = (agent_row.scope or "").lower()
        scope_id_val = agent_row.scope_id
        if scope_str == "crew" and scope_id_val:
            from src.services.authorization import Authorization

            await Authorization(db).assert_content_access(
                current_user, crew_id=UUID(str(scope_id_val))
            )
        elif scope_str == "space" and scope_id_val:
            from src.services.authorization import Authorization

            await Authorization(db).assert_content_access(
                current_user, space_id=UUID(str(scope_id_val))
            )
        elif scope_str == "personal" and agent_row.created_by != current_user.id:
            from src.core.exceptions import ForbiddenError

            raise ForbiddenError("You cannot view this agent's findings.")
    return await service.list_findings(agent_id, include_dismissed=include_dismissed)


@router.get("/{agent_id}/metrics")
async def get_agent_metrics(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Per-agent usage metrics.

    Two flavours of volume surface here:

    * `runs_*` and `data_bytes_*` — human-readable units shown to end
      users in the agent card. "This agent ran 12 times and analyzed
      8 MB of data this month."
    * `tokens_*` — technical LLM units, used only by admin-level
      billing screens and the customer invoice. Included in the
      response so the same endpoint powers both views, but the
      end-user UI never surfaces it.

    SECURITY (audit 2026-05-05): the previous implementation gated on
    a global ``agents.view`` check, never verifying the caller could
    actually access THIS specific agent. Resolve the agent first and
    pass its space scope into the RBAC check so the existing
    list-agents IDOR fix (which scopes to ``created_by`` for non-admins)
    is enforced here too.
    """
    agent_q_pre = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent_pre = agent_q_pre.scalar_one_or_none()
    if not agent_pre:
        raise HTTPException(status_code=404, detail="Agent not found")
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent_pre, "scope", None),
        scope_id=getattr(agent_pre, "scope_id", None),
        permission="agents.view",
    )
    # Belt-and-suspenders: the helper already enforces owner-or-admin
    # for personal agents (matching ``scope_id`` against the caller),
    # but the legacy ``created_by`` IDOR guard stays as a second layer
    # in case a personal agent ever lands with a stale ``scope_id``.
    is_org_admin = (current_user.role or "").lower() in TENANT_ADMIN_ROLES
    if (
        agent_pre.scope == "personal"
        and not is_org_admin
        and agent_pre.created_by != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Not allowed for this agent")
    import json
    from datetime import datetime, timezone

    from src.models.agent import AgentExecution

    exec_q = await db.execute(select(AgentExecution).where(AgentExecution.agent_id == agent_id))
    executions = list(exec_q.scalars().all())

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _month(e: AgentExecution) -> bool:
        started = getattr(e, "started_at", None) or getattr(e, "created_at", None)
        return bool(started and started >= month_start)

    def _tokens(e: AgentExecution) -> int:
        return int(e.llm_tokens_used or 0) + int(e.delta_tokens or 0)

    def _data_bytes(e: AgentExecution) -> int:
        """Size of the query result the execution analyzed. We use the
        JSONB result_payload byte length as the proxy: it captures both
        rows read and any intermediate aggregation the agent touched."""
        payload = getattr(e, "result_payload", None)
        if payload is None:
            return 0
        # Desde 13/10/2026 a corrida guarda o tamanho e não as linhas.
        if isinstance(payload, dict) and isinstance(payload.get("data_bytes"), int):
            return int(payload["data_bytes"])
        try:
            return len(json.dumps(payload, default=str))
        except Exception:
            return 0

    runs_total = len(executions)
    runs_this_month = sum(1 for e in executions if _month(e))
    tokens_total = sum(_tokens(e) for e in executions)
    tokens_this_month = sum(_tokens(e) for e in executions if _month(e))
    data_bytes_total = sum(_data_bytes(e) for e in executions)
    data_bytes_this_month = sum(_data_bytes(e) for e in executions if _month(e))
    findings_total = sum(int(e.findings_count or 0) for e in executions)
    findings_this_month = sum(int(e.findings_count or 0) for e in executions if _month(e))
    durations = [e.duration_ms for e in executions if e.duration_ms]
    avg_duration_ms = int(sum(durations) / len(durations)) if durations else None
    last_execution = next(
        (
            e
            for e in sorted(
                executions,
                key=lambda x: (
                    getattr(x, "started_at", None)
                    or getattr(x, "created_at", None)
                    or datetime.min.replace(tzinfo=timezone.utc)
                ),
                reverse=True,
            )
        ),
        None,
    )

    agent_q = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_q.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "agent_id": str(agent_id),
        "runs_total": runs_total,
        "runs_this_month": runs_this_month,
        "data_bytes_total": data_bytes_total,
        "data_bytes_this_month": data_bytes_this_month,
        "avg_data_bytes_per_run": int(data_bytes_total / runs_total) if runs_total else 0,
        "findings_total": findings_total,
        "findings_this_month": findings_this_month,
        "avg_duration_ms": avg_duration_ms,
        "last_run_at": (
            (
                getattr(last_execution, "started_at", None)
                or getattr(last_execution, "created_at", None)
            )
            if last_execution
            else None
        ),
        "next_run_at": agent.next_execution_at,
        "connection_count": len(agent.connection_ids or []),
        "table_count": len(agent.table_ids or []),
        # Billing-only fields. End-user UI must NOT surface these; they
        # are aggregated by the tenant admin dashboard and printed on
        # the customer invoice.
        "tokens_total": tokens_total,
        "tokens_this_month": tokens_this_month,
        "avg_tokens_per_run": int(tokens_total / runs_total) if runs_total else 0,
    }


@router.get("/metrics/summary")
async def get_tenant_agent_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Tenant-level roll-up for Settings → Usage & Metrics.

    Aggregates runs and tokens across every agent the user can see so
    admins can show customers a single "you used X runs / Y tokens this
    month" number per billing cycle.

    SECURITY (audit 2026-05-05): the previous implementation served the
    SAME numbers to every caller with ``metrics.view``, so a regular
    member with ``metrics.view`` saw billing-grade aggregates spanning
    agents they could not otherwise read. We now scope the aggregation
    to agents the caller can access — same shape as ``list_agents``:
      • org admin / owner → entire tenant (existing behaviour)
      • everyone else → personal agents they own + space agents in
        their member spaces.
    """
    await RBACService(db).assert_permission(current_user, "metrics.view")
    from datetime import datetime, timezone

    from src.models.agent import AgentExecution

    is_org_admin = (current_user.role or "").lower() in TENANT_ADMIN_ROLES
    agent_query = select(Agent)
    if not is_org_admin:
        from sqlalchemy import and_, or_

        from src.models.space import SpaceMember

        member_q = await db.execute(
            select(SpaceMember.space_id).where(SpaceMember.user_id == current_user.id)
        )
        member_space_ids = [str(sid) for sid in member_q.scalars().all()]
        clauses = [Agent.created_by == current_user.id]
        if member_space_ids:
            clauses.append(
                and_(
                    Agent.scope == "space",
                    Agent.scope_id.in_(member_space_ids),
                )
            )
        agent_query = agent_query.where(or_(*clauses))

    all_agents = await db.execute(agent_query)
    agents = list(all_agents.scalars().all())

    visible_agent_ids = [a.id for a in agents]
    if visible_agent_ids:
        execs_q = await db.execute(
            select(AgentExecution).where(AgentExecution.agent_id.in_(visible_agent_ids))
        )
        executions = list(execs_q.scalars().all())
    else:
        executions = []

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _month(e: AgentExecution) -> bool:
        started = getattr(e, "started_at", None) or getattr(e, "created_at", None)
        return bool(started and started >= month_start)

    def _tokens(e: AgentExecution) -> int:
        return int(e.llm_tokens_used or 0) + int(e.delta_tokens or 0)

    import json

    def _data_bytes(e: AgentExecution) -> int:
        payload = getattr(e, "result_payload", None)
        if payload is None:
            return 0
        # Desde 13/10/2026 a corrida guarda o tamanho e não as linhas.
        if isinstance(payload, dict) and isinstance(payload.get("data_bytes"), int):
            return int(payload["data_bytes"])
        try:
            return len(json.dumps(payload, default=str))
        except Exception:
            return 0

    return {
        "agents_total": len(agents),
        "agents_active": sum(1 for a in agents if a.status == "active"),
        "runs_this_month": sum(1 for e in executions if _month(e)),
        "runs_total": len(executions),
        "data_bytes_this_month": sum(_data_bytes(e) for e in executions if _month(e)),
        "data_bytes_total": sum(_data_bytes(e) for e in executions),
        "findings_this_month": sum(int(e.findings_count or 0) for e in executions if _month(e)),
        "findings_total": sum(int(e.findings_count or 0) for e in executions),
        # Billing-only — admin invoice / backend cost projection.
        "tokens_this_month": sum(_tokens(e) for e in executions if _month(e)),
        "tokens_total": sum(_tokens(e) for e in executions),
    }


@router.post("/{agent_id}/findings/{finding_id}/dismiss", response_model=AgentFindingResponse)
async def dismiss_finding(
    agent_id: UUID,
    finding_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """Dismiss a finding — só um achado DESTE agente, e só quem pode no âmbito dele.

    Antes bastava a permissão genérica do cliente (`agents.findings.dismiss`)
    e o `agent_id` do caminho era ignorado: qualquer membro com essa
    permissão arquivava o achado de QUALQUER agente, de qualquer equipa,
    sabendo o id — bastava pô-lo atrás do id de um agente seu. Ler um achado
    exige ser membro da equipa/projeto do agente (`list_findings`); arquivar
    não pode exigir menos.
    """
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    from src.models.agent import AgentFinding

    achado = (
        await db.execute(
            select(AgentFinding.id).where(
                AgentFinding.id == finding_id, AgentFinding.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if achado is None:
        # O mesmo 404 de «não existe»: não se confirma que o id é de outro.
        raise HTTPException(status_code=404, detail="Finding not found")

    # A mesma porta da leitura (conteúdo: membro real da equipa/projeto, sem
    # atalho de administrador) e a permissão no âmbito do agente.
    ambito = (agent.scope or "").lower()
    if ambito in ("crew", "space"):
        if not await _is_content_member(db, current_user, ambito, agent.scope_id):
            raise HTTPException(
                status_code=403, detail="You cannot act on this agent's findings."
            )
    elif ambito == "personal" and agent.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="You cannot act on this agent's findings.")
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.findings.dismiss",
    )
    return await service.dismiss_finding(finding_id)


@router.post(
    "/{agent_id}/findings/{finding_id}/add-to-page",
    response_model=AddFindingToPageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_finding_to_page(
    agent_id: UUID,
    finding_id: UUID,
    payload: AddFindingToPageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: AgentService = Depends(get_agent_service),
):
    """Materialise an agent finding as a Widget on the target page.

    Before this endpoint existed the FE "Add to page" CTA fell back to
    the generic POST /widgets endpoint with type='text', so charts and
    KPIs were lost — only the description ended up on the page. This
    endpoint reads the finding's viz_kind + rows and builds a typed
    Widget (chart / kpi / table / insight) so the canvas renders the
    same visualisation the user saw in the Cockpit. The agent's first
    connection is propagated so the widget can refresh later.
    """
    # Permission: the caller must be allowed to act on the agent (so a
    # crew/space agent can be added to a page by any member) and must
    # be the page owner / member. We reuse the existing helpers rather
    # than open-coding ACL here.
    agent = await service.get_agent(agent_id)
    await _assert_can_act_on_agent_scope(
        db,
        current_user,
        scope=getattr(agent, "scope", None),
        scope_id=getattr(agent, "scope_id", None),
        permission="agents.findings.view",
    )

    result = await service.add_finding_to_page(
        agent_id=agent_id,
        finding_id=finding_id,
        page_id=payload.page_id,
        user=current_user,
        position=payload.position,
        size=payload.size,
    )
    return AddFindingToPageResponse(**result)
