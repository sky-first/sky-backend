"""Public demo signup endpoint — Cenário B (per-visitor sandbox).

POST /demo/signup is the only path a non-authenticated visitor has into
the platform. Anti-fraud is layered: server-side Turnstile verification,
per-IP rate limit, throwaway-email block list.

The endpoint is intentionally NOT mounted behind get_current_user — it
issues the JWT itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.params import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.space import Space
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.demo import DemoSignupRequest, DemoSignupResponse
from src.schemas.demo_content import (
    DemoAnswerResponse,
    DemoAskRequest,
    DemoBootstrapResponse,
    DemoInsightModel,
    DemoLeadRequest,
    DemoLeadResponse,
    SuggestedQuestion,
)
from src.services import demo_content_service
from src.services.demo_service import DemoService

router = APIRouter()


def _client_ip(request: Request) -> Optional[str]:
    """Extracts the visitor IP, honouring X-Forwarded-For when set by the
    ingress. Returns None when nothing is reachable (used for tests)."""
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post(
    "/signup",
    response_model=DemoSignupResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
    summary="Public demo signup",
    description=(
        "Provisions a per-visitor sandbox (Space + guest user) and returns a "
        "JWT pair. Requires a valid Cloudflare Turnstile token. Rate-limited "
        "per source IP. Returning visitors with the same email get their "
        "existing sandbox re-issued instead of a fresh one."
    ),
)
async def signup(
    payload: DemoSignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DemoSignupResponse:
    # Demo is platform-only. Real customer tenants (e.g. gbtsolutions) have
    # ``feature_flags.demo_enabled = false``; the front-end hides the demo
    # link (auth.py show_demo), but this endpoint MUST enforce it too —
    # otherwise anyone can POST /demo/signup and provision a demo Space
    # inside a real tenant (a "Demo Sky" space appeared in gbtsolutions
    # exactly this way: the global settings.DEMO_ENABLED was the only gate).
    # The default/platform context keeps the public demo open.
    ctx = getattr(request.state, "tenant_context", None)
    if ctx is not None and not getattr(ctx, "is_default", False):
        flags = getattr(ctx, "feature_flags", None) or {}
        if not flags.get("demo_enabled", False):
            raise ForbiddenError("Demo is not available on this workspace.")

    service = DemoService(db)
    return await service.signup(
        payload=payload,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/{user_id}/extend",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Extend a demo user's TTL by N days",
    description=(
        "Owner / Admin only. Pushes both the user's `demo_expires_at` and "
        "their demo Space's `demo_expires_at` forward by `days` (default 7). "
        "Idempotent on a single click — the new TTL is `max(now, current_ttl) "
        "+ days` so re-clicking doesn't shrink the window. Lucas's "
        "2026-04-30 brief: 'extend by 7 days do lado da conta do usuario na "
        "tela de settings > member'."
    ),
)
async def extend_demo_user(
    user_id: UUID,
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if current_user.role not in ("owner", "admin", "super_admin"):
        raise ForbiddenError("Only the tenant Owner or an Admin can extend a demo TTL.")
    if days <= 0 or days > 90:
        raise BadRequestError("`days` must be between 1 and 90.")

    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None or not getattr(target, "is_demo", False):
        raise NotFoundError("Demo user not found.")

    now = datetime.now(timezone.utc)
    base = (
        target.demo_expires_at if target.demo_expires_at and target.demo_expires_at > now else now
    )
    new_ttl = base + timedelta(days=days)
    target.demo_expires_at = new_ttl

    # The Space the user owns shares the TTL — keep them in sync so the
    # cleanup cron doesn't reap the Space mid-extension.
    space_q = await db.execute(
        select(Space).where(Space.created_by == target.id, Space.is_demo.is_(True))
    )
    space = space_q.scalars().first()
    if space is not None:
        space.demo_expires_at = new_ttl

    await db.commit()

    # audit_events row so the "who extended which user when" is traceable.
    try:
        from src.services.audit_service import AuditService

        await AuditService(db).log_event(
            actor_kind="user",
            actor_id=current_user.id,
            actor_email=current_user.email,
            action="demo.user.extended",
            resource_kind="user",
            resource_id=str(target.id),
            decision="allow",
            decision_reason=f"days={days}",
            metadata={
                "target_email": target.email,
                "new_demo_expires_at": new_ttl.isoformat(),
            },
        )
    except Exception:
        pass

    return {
        "user_id": str(target.id),
        "email": target.email,
        "demo_expires_at": new_ttl.isoformat(),
        "extended_by_days": days,
    }


@router.post(
    "/reseed-space/{space_id}",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Re-run the demo seed on an existing Space",
    description=(
        "Owner / Admin only. Idempotently re-applies every demo seed step "
        "(connections → knowledge → agents → findings) to the supplied "
        "Space. Use this to heal a Space whose Sources / Agents panel "
        "ended up empty because the DEMO_DATASET_CONNECTION_IDS env var "
        "was missing or pointed at stale UUIDs when the visitor signed "
        "up. Each underlying step is idempotent so the action is safe "
        "to retry. Returns the counts of what was added."
    ),
)
async def reseed_space(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if current_user.role not in ("owner", "admin", "super_admin"):
        raise ForbiddenError("Only the tenant Owner or an Admin can reseed a demo Space.")
    return await DemoService(db).reseed_space(space_id, current_user)


# ─── Conteúdo curado (BE-12) ─────────────────────────────────────────────
#
# Endpoints públicos, sem autenticação e sem captcha. Servem conteúdo
# curado sobre datasets sintéticos — não tocam em dados de tenant e não
# provisionam nada.
#
# Não provisionar é o que torna seguro remover o captcha da entrada: até
# o visitante carregar dados próprios não há sandbox, não há base de
# dados e não há custo. Um script que martele estes endpoints consome
# cache, não recursos.


def _demo_rate_ok(request: Request, bucket: str, limit: int) -> bool:
    from src.services.demo_service import _check_ip_rate_limit

    return _check_ip_rate_limit(f"{bucket}:{_client_ip(request) or ''}", limit)


@router.get(
    "/bootstrap",
    response_model=DemoBootstrapResponse,
    summary="Conteúdo de entrada da demo (público, cacheável)",
    description=(
        "Devolve o insight herói e as perguntas sugeridas para uma vertical. "
        "Não toca no motor de AI — é conteúdo curado, servido estático. "
        "Uma vertical desconhecida devolve o dataset de omissão, nunca 404."
    ),
)
async def demo_bootstrap(
    response: Response,
    vertical: Optional[str] = Query(None, max_length=32),
    locale: str = Query("en", max_length=10),
    db: AsyncSession = Depends(get_db_session),
) -> DemoBootstrapResponse:
    dataset = await demo_content_service.get_dataset(db, vertical=vertical, locale=locale)
    if dataset is None:
        # Sem conteúdo curado ainda. 503 e não 404: a rota existe, falta
        # o conteúdo — e é isso que o frontend precisa de distinguir.
        raise HTTPException(
            status_code=503,
            detail="Demo content not seeded yet.",
        )

    insight = await demo_content_service.get_insight(db, dataset.id)
    suggested = await demo_content_service.get_suggested(db, dataset.id)

    # Cacheável em CDN: o conteúdo é o mesmo para toda a gente e muda
    # apenas quando alguém corre a curadoria.
    response.headers["Cache-Control"] = "public, max-age=300"

    return DemoBootstrapResponse(
        dataset_id=str(dataset.id),
        vertical=dataset.vertical,
        locale=dataset.locale,
        insight=_insight_to_model(insight) if insight else None,
        suggested_questions=[
            SuggestedQuestion(id=str(q.id), question=q.question) for q in suggested
        ],
    )


@router.get(
    "/answer/{qa_id}",
    response_model=DemoAnswerResponse,
    summary="Resposta pré-calculada a uma pergunta sugerida",
)
async def demo_answer(
    qa_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> DemoAnswerResponse:
    qa = await demo_content_service.get_qa(db, qa_id)
    if qa is None:
        raise NotFoundError("Answer not found.")
    response.headers["Cache-Control"] = "public, max-age=300"
    return _qa_to_model(qa, is_fallback=False)


@router.post(
    "/ask",
    response_model=DemoAnswerResponse,
    summary="Pergunta livre, com queda para conteúdo curado",
    description=(
        "Tenta responder ao vivo. Se o motor exceder o tempo ou falhar, "
        "devolve a resposta curada mais próxima com is_fallback=true. "
        "Nunca devolve erro de motor ao visitante."
    ),
)
async def demo_ask(
    payload: DemoAskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DemoAnswerResponse:
    if not _demo_rate_ok(request, "demo:ask", 10):
        raise HTTPException(status_code=429, detail="Too many questions. Try again later.")

    try:
        dataset_id = UUID(payload.dataset_id)
    except (ValueError, AttributeError):
        raise BadRequestError("Invalid dataset_id.")

    qa, live, is_fallback = await demo_content_service.ask(
        db, dataset_id=dataset_id, question=payload.question
    )

    if live is not None:
        return DemoAnswerResponse(
            id=live.get("id", ""),
            question=payload.question,
            answer_markdown=live.get("answer_markdown", ""),
            citations=live.get("citations", []),
            chart_spec=live.get("chart_spec"),
            executed_sql=live.get("executed_sql"),
            is_fallback=False,
        )

    if qa is None:
        # Sem conteúdo curado para cair. Devolve uma resposta honesta em
        # vez de 500 — o visitante não pode ver um ecrã de erro.
        return DemoAnswerResponse(
            id="",
            question=payload.question,
            answer_markdown=(
                "This demo dataset doesn't cover that question yet. "
                "Try one of the suggested questions, or bring your own data."
            ),
            is_fallback=True,
        )

    return _qa_to_model(qa, is_fallback=is_fallback, question=payload.question)


@router.post(
    "/lead",
    response_model=DemoLeadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Contacto deixado depois de ver valor",
)
async def demo_lead(
    payload: DemoLeadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DemoLeadResponse:
    if not _demo_rate_ok(request, "demo:lead", 5):
        raise HTTPException(status_code=429, detail="Too many submissions. Try again later.")

    dataset_id = None
    if payload.dataset_id:
        try:
            dataset_id = UUID(payload.dataset_id)
        except ValueError:
            dataset_id = None

    await demo_content_service.record_lead(
        db,
        email=str(payload.email),
        dataset_id=dataset_id,
        questions_asked=payload.questions_asked,
        vertical=payload.vertical,
        locale=payload.locale,
        source=payload.source,
    )
    return DemoLeadResponse(accepted=True)


def _insight_to_model(i) -> DemoInsightModel:
    return DemoInsightModel(
        id=str(i.id),
        severity=i.severity,
        severity_level=i.severity_level,
        agent_name=i.agent_name,
        title=i.title,
        summary=i.summary,
        series=i.series or None,
        stat_tiles=i.stat_tiles or [],
        sources=i.sources or [],
        executed_sql=i.executed_sql,
    )


def _qa_to_model(q, *, is_fallback: bool, question: Optional[str] = None) -> DemoAnswerResponse:
    return DemoAnswerResponse(
        id=str(q.id),
        question=question or q.question,
        answer_markdown=q.answer_markdown,
        citations=q.citations or [],
        chart_spec=q.chart_spec,
        executed_sql=q.executed_sql,
        is_fallback=is_fallback,
    )
