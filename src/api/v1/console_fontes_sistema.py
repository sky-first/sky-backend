"""Consola — fontes do sistema (dados públicos activados por cliente).

Contrato: ``docs/contrato-fontes-do-sistema.md``. Montado em
``/api/console/v1`` ao lado do ``console.py``.

Com ``FONTES_SISTEMA_ENABLED=false`` todas as rotas respondem 404
``{"error": "fontes_sistema_desligadas"}`` — a Consola esconde a secção.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.console_auth import audit_action, require_sky_team
from src.api.deps import get_db_session
from src.config.settings import settings
from src.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from src.models.fonte_sistema import FonteSistema, FonteSistemaCliente
from src.models.internal_console import AuditAction, AuditResult
from src.models.tenant import Tenant
from src.models.user import User
from src.services import console_rbac, planos
from src.services.fontes_sistema.catalogo import (
    FonteInvalidaError,
    plano_permite,
    validar_para_ativar,
)

logger = logging.getLogger(__name__)
router = APIRouter()

TAREFA_CONVERGIR = "src.workers.fontes_sistema_worker.provisionar_fontes_do_cliente"


# ── Esquemas ─────────────────────────────────────────────────────────


class Frescura(BaseModel):
    estado: Optional[str] = None  # ok | erro | sem_chave | desconhecido
    dado_de: Optional[datetime] = None
    ultima_actualizacao: Optional[datetime] = None
    linhas: Optional[int] = None
    atrasada: bool = False
    erro: Optional[str] = None


class FonteDoCatalogo(BaseModel):
    id: str
    nome: Dict[str, Any]
    descricao: Optional[Dict[str, Any]] = None
    tipo: str
    estado: str
    tabelas: List[str]
    licenca: Optional[str] = None
    atribuicao: Optional[Dict[str, Any]] = None
    uso_comercial: bool
    cadencia_min: Optional[int] = None
    planos_permitidos: List[str]
    conta_como_fonte: bool
    versao: int
    frescura: Optional[Frescura] = None
    clientes_ativos: int = 0


class Catalogo(BaseModel):
    fontes: List[FonteDoCatalogo]
    frescura_disponivel: bool


class FonteDoCliente(BaseModel):
    fonte_id: str
    nome: Dict[str, Any]
    tipo: str
    estado_catalogo: str
    ativa: bool
    #: a_preparar | pronta | erro | a_desligar | desligada | nunca_ativada
    estado: str
    erro: Optional[Dict[str, Any]] = None
    permitida_pelo_plano: bool
    ativavel: bool
    motivo_nao_ativavel: Optional[str] = None
    frescura: Optional[Frescura] = None
    ativada_por: Optional[str] = None
    ativada_em: Optional[datetime] = None
    desativada_por: Optional[str] = None
    desativada_em: Optional[datetime] = None
    pronta_em: Optional[datetime] = None
    actualizado_em: Optional[datetime] = None


class FontesDoCliente(BaseModel):
    slug: str
    plano: Optional[str] = None
    fontes: List[FonteDoCliente]
    frescura_disponivel: bool


class PedidoDeActivacao(BaseModel):
    ativa: bool


class RespostaDeActivacao(BaseModel):
    fonte_id: str
    ativa: bool
    estado: str
    job_id: Optional[str] = None


class RespostaDeReconciliacao(BaseModel):
    slug: str
    job_id: Optional[str] = None


# ── Erros com ``error.details.reason`` (o envelope de toda a API) ────


def _com_razao(cls, mensagem: str, reason: str, **extra):
    exc = cls(mensagem)
    exc.details = {"reason": reason, **extra}
    return exc


# ── Ajudas ───────────────────────────────────────────────────────────


def _exigir_ligado() -> None:
    if not settings.FONTES_SISTEMA_ENABLED:
        raise _com_razao(NotFoundError, "Fontes do sistema desligadas", "fontes_sistema_desligadas")


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


async def _exigir_permissao(db: AsyncSession, user: User, acao: str) -> None:
    roles = await console_rbac.load_active_roles(db, user.email)
    if not console_rbac.has_permission(roles, acao):
        raise _com_razao(
            ForbiddenError,
            "Sem permissão para esta acção",
            "permission_denied",
            required_action=acao,
            user_roles=[r.value for r in roles],
        )


async def _ler_frescura() -> Optional[Dict[str, dict]]:
    """``mundo.fontes`` por nome do carregador, ou ``None`` se não deu para ler."""
    if not settings.WORLD_ADMIN_DSN:
        return None
    from src.services.fontes_sistema.mundo import Mundo

    try:
        async with Mundo() as m:
            return await m.frescura()
    except Exception as exc:  # noqa: BLE001 — a Consola mostra «sem dados de frescura»
        logger.warning("fontes_sistema: frescura indisponível: %s", type(exc).__name__)
        return None


def _frescura_da_fonte(fonte: FonteSistema, mapa: Optional[Dict[str, dict]]) -> Optional[Frescura]:
    if mapa is None:
        return None
    nomes = list(fonte.nome_carregador or [])
    if not nomes:
        return None
    linhas = [mapa.get(n) for n in nomes]
    if any(l is None for l in linhas):
        return Frescura(estado="desconhecido", atrasada=True)
    # A pior das cargas que alimentam a fonte.
    datas = [l.get("dado_de") or l.get("ultima_actualizacao") for l in linhas]
    mais_velha = min((d for d in datas if d is not None), default=None)
    erro = next((l.get("erro") for l in linhas if l.get("estado") == "erro"), None)
    estado = (
        "erro"
        if erro
        else ("sem_chave" if any(l.get("estado") == "sem_chave" for l in linhas) else "ok")
    )
    atrasada = True
    if mais_velha is not None and fonte.cadencia_min:
        if mais_velha.tzinfo is None:
            mais_velha = mais_velha.replace(tzinfo=timezone.utc)
        atrasada = datetime.now(timezone.utc) - mais_velha > timedelta(
            minutes=2 * fonte.cadencia_min
        )
    elif mais_velha is not None:
        atrasada = False
    return Frescura(
        estado=estado,
        dado_de=mais_velha,
        ultima_actualizacao=max(
            (l.get("ultima_actualizacao") for l in linhas if l.get("ultima_actualizacao")),
            default=None,
        ),
        linhas=sum(int(l.get("linhas") or 0) for l in linhas),
        atrasada=atrasada,
        erro=(erro or None) and str(erro)[:300],
    )


async def _cliente(db: AsyncSession, slug: str) -> Tenant:
    t = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if t is None:
        raise _com_razao(NotFoundError, "Cliente desconhecido", "tenant_not_found")
    return t


def _ativavel(fonte: FonteSistema, plano: Optional[str]) -> tuple[bool, Optional[str]]:
    try:
        validar_para_ativar(fonte)
    except FonteInvalidaError as exc:
        return False, exc.motivo
    if not plano_permite(fonte, plano):
        return False, "plano_nao_permite"
    return True, None


def _item(
    fonte: FonteSistema,
    row: Optional[FonteSistemaCliente],
    plano: Optional[str],
    mapa: Optional[Dict[str, dict]],
) -> FonteDoCliente:
    ativavel, motivo = _ativavel(fonte, plano)
    return FonteDoCliente(
        fonte_id=fonte.id,
        nome=fonte.nome or {},
        tipo=fonte.tipo,
        estado_catalogo=fonte.estado,
        ativa=bool(row and row.ativa),
        estado=row.estado if row else "nunca_ativada",
        erro=row.erro if row else None,
        permitida_pelo_plano=plano_permite(fonte, plano),
        ativavel=ativavel,
        motivo_nao_ativavel=motivo,
        frescura=_frescura_da_fonte(fonte, mapa),
        ativada_por=row.ativada_por if row else None,
        ativada_em=row.ativada_em if row else None,
        desativada_por=row.desativada_por if row else None,
        desativada_em=row.desativada_em if row else None,
        pronta_em=row.pronta_em if row else None,
        actualizado_em=row.actualizado_em if row else None,
    )


def _enfileirar(slug: str) -> Optional[str]:
    from src.workers.celery_app import celery_app

    r = celery_app.send_task(TAREFA_CONVERGIR, args=[slug])
    return getattr(r, "id", None)


# ── Rotas ────────────────────────────────────────────────────────────


@router.get("/fontes-sistema", response_model=Catalogo, summary="Catálogo de fontes do sistema")
async def listar_catalogo(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> Catalogo:
    _exigir_ligado()
    fontes = (await db.execute(select(FonteSistema).order_by(FonteSistema.id))).scalars().all()
    contagem = dict(
        (
            await db.execute(
                select(FonteSistemaCliente.fonte_id, func.count())
                .where(FonteSistemaCliente.ativa.is_(True))
                .group_by(FonteSistemaCliente.fonte_id)
            )
        ).all()
    )
    mapa = await _ler_frescura()
    return Catalogo(
        frescura_disponivel=mapa is not None,
        fontes=[
            FonteDoCatalogo(
                id=f.id,
                nome=f.nome or {},
                descricao=f.descricao,
                tipo=f.tipo,
                estado=f.estado,
                tabelas=list(f.tabelas or []),
                licenca=f.licenca,
                atribuicao=f.atribuicao,
                uso_comercial=bool(f.uso_comercial),
                cadencia_min=f.cadencia_min,
                planos_permitidos=list(f.planos_permitidos or []),
                conta_como_fonte=bool(f.conta_como_fonte),
                versao=f.versao or 1,
                frescura=_frescura_da_fonte(f, mapa),
                clientes_ativos=int(contagem.get(f.id, 0)),
            )
            for f in fontes
        ],
    )


@router.get(
    "/tenants/{slug}/fontes-sistema",
    response_model=FontesDoCliente,
    summary="Fontes do sistema de um cliente, com estado",
)
async def listar_do_cliente(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> FontesDoCliente:
    _exigir_ligado()
    tenant = await _cliente(db, slug)
    plano = planos.normalizar(tenant.tier)
    fontes = (
        (
            await db.execute(
                select(FonteSistema)
                .where(FonteSistema.estado != "retirada")
                .order_by(FonteSistema.id)
            )
        )
        .scalars()
        .all()
    )
    linhas = {
        r.fonte_id: r
        for r in (
            await db.execute(
                select(FonteSistemaCliente).where(FonteSistemaCliente.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    }
    # Uma fonte retirada do catálogo que o cliente ainda tem aparece na mesma.
    for fid in set(linhas) - {f.id for f in fontes}:
        f = await db.get(FonteSistema, fid)
        if f is not None:
            fontes.append(f)
    mapa = await _ler_frescura()
    return FontesDoCliente(
        slug=slug,
        plano=plano,
        frescura_disponivel=mapa is not None,
        fontes=[_item(f, linhas.get(f.id), plano, mapa) for f in fontes],
    )


@router.get(
    "/tenants/{slug}/fontes-sistema/{fonte_id}",
    response_model=FonteDoCliente,
    summary="Estado de uma fonte num cliente (para poll)",
)
async def estado_no_cliente(
    slug: str,
    fonte_id: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> FonteDoCliente:
    _exigir_ligado()
    tenant = await _cliente(db, slug)
    fonte = await db.get(FonteSistema, fonte_id)
    if fonte is None:
        raise _com_razao(NotFoundError, "Fonte desconhecida", "fonte_not_found")
    row = await db.get(FonteSistemaCliente, (tenant.id, fonte_id))
    return _item(fonte, row, planos.normalizar(tenant.tier), await _ler_frescura())


@router.put(
    "/tenants/{slug}/fontes-sistema/{fonte_id}",
    response_model=RespostaDeActivacao,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Marcar / desmarcar uma fonte num cliente",
)
async def marcar(
    slug: str,
    fonte_id: str,
    payload: PedidoDeActivacao,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> RespostaDeActivacao:
    _exigir_ligado()
    await _exigir_permissao(db, user, "system_sources.toggle")
    tenant = await _cliente(db, slug)
    fonte = await db.get(FonteSistema, fonte_id)
    if fonte is None:
        raise _com_razao(NotFoundError, "Fonte desconhecida", "fonte_not_found")
    acao = AuditAction.ENABLE_SYSTEM_SOURCE if payload.ativa else AuditAction.DISABLE_SYSTEM_SOURCE

    if payload.ativa:
        plano = planos.normalizar(tenant.tier)
        ativavel, motivo = _ativavel(fonte, plano)
        if not ativavel:
            await audit_action(
                db,
                actor=user,
                action=acao,
                tenant_slug=slug,
                result=AuditResult.FAILURE,
                request_payload={"fonte_id": fonte_id, "ativa": True},
                result_details={"reason": motivo},
                actor_ip=_ip(request),
            )
            await db.commit()
            raise _com_razao(
                ConflictError,
                "Esta fonte não pode ser activada neste cliente",
                motivo or "nao_ativavel",
                fonte_id=fonte_id,
                plano=plano,
            )

    # FOR UPDATE: dois operadores no mesmo cliente serializam aqui (S17).
    q = select(FonteSistemaCliente).where(
        FonteSistemaCliente.tenant_id == tenant.id, FonteSistemaCliente.fonte_id == fonte_id
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        q = q.with_for_update()
    row = (await db.execute(q)).scalar_one_or_none()
    agora = datetime.now(timezone.utc)

    if row is None and not payload.ativa:
        # Nunca esteve activa: nada a desligar, nada a enfileirar.
        return RespostaDeActivacao(fonte_id=fonte_id, ativa=False, estado="desligada")

    if row is None:
        row = FonteSistemaCliente(tenant_id=tenant.id, fonte_id=fonte_id)
        db.add(row)
    row.ativa = payload.ativa
    row.pedido_id = uuid.uuid4()
    row.erro = None
    if payload.ativa:
        row.estado = "a_preparar"
        row.ativada_por, row.ativada_em = user.email, agora
    else:
        row.estado = "a_desligar"
        row.desativada_por, row.desativada_em = user.email, agora
    await db.flush()
    await audit_action(
        db,
        actor=user,
        action=acao,
        tenant_slug=slug,
        result=AuditResult.SUCCESS,
        request_payload={"fonte_id": fonte_id, "ativa": payload.ativa, "versao": fonte.versao},
        actor_ip=_ip(request),
    )
    # Grava ANTES de enfileirar: a tarefa lê o pedido da base.
    await db.commit()
    job_id = _enfileirar(slug)
    return RespostaDeActivacao(
        fonte_id=fonte_id, ativa=payload.ativa, estado=row.estado, job_id=job_id
    )


@router.post(
    "/tenants/{slug}/fontes-sistema/reconciliar",
    response_model=RespostaDeReconciliacao,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reconciliar já (refrescar o estado) as fontes de um cliente",
)
async def reconciliar(
    slug: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> RespostaDeReconciliacao:
    _exigir_ligado()
    await _exigir_permissao(db, user, "system_sources.toggle")
    await _cliente(db, slug)
    await audit_action(
        db,
        actor=user,
        action=AuditAction.RECONCILE_SYSTEM_SOURCES,
        tenant_slug=slug,
        result=AuditResult.SUCCESS,
        actor_ip=_ip(request),
    )
    await db.commit()
    return RespostaDeReconciliacao(slug=slug, job_id=_enfileirar(slug))
