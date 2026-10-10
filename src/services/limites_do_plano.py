"""O plano de cada cliente, a bloquear a sério.

> «Tudo isso tem que bloquear.» — Lucas, 10/10/2026

Ver `docs/PLANOS_E_LIMITES_2026-10.md`.

── Porque é que isto abre uma sessão própria ───────────────────────────────

O plano vive na base da PLATAFORMA, onde só a Consola escreve. A sessão que
chega às rotas (`get_db_session`) já está encaminhada para a base do
CLIENTE — e era lá que o `pricing_service.get_limits` lia, e lá criava
sozinho uma linha «enterprise sem tecto». Medido a 10/10: o sandbox, em
Starter no registo, era servido sem limite nenhum, e todos os outros também.

Por isso: tudo o que é plano lê-se e escreve-se com `AsyncSessionLocal`
(a plataforma). O que se CONTA (ligações, agentes) conta-se na base do
cliente, que é onde essas linhas vivem.

── Falha fechada ───────────────────────────────────────────────────────────

Sem plano conhecido, não se serve. «Ilimitado por omissão» foi exactamente
o defeito. A excepção é o modo de um só cliente (local e testes), onde não
há registo nenhum de clientes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import PaymentRequiredError, ServiceUnavailableError
from src.models.tenant_plan_limits import TenantPlanLimits
from src.services import planos

logger = logging.getLogger(__name__)

#: O mês das perguntas vira à meia-noite de Lisboa/Madrid, não de UTC.
FUSO_DO_MES = ZoneInfo("Europe/Madrid")


# ── O erro que o cliente vê ─────────────────────────────────────────────

_NOMES = {
    "max_connections": {"pt": "fontes de dados", "es": "fuentes de datos", "en": "data sources"},
    "max_agents": {"pt": "áreas vigiadas", "es": "áreas vigiladas", "en": "watched areas"},
    "max_queries_per_month": {
        "pt": "perguntas este mês",
        "es": "preguntas este mes",
        "en": "questions this month",
    },
    "max_storage_gb": {
        "pt": "GB de armazenamento",
        "es": "GB de almacenamiento",
        "en": "GB of storage",
    },
}


def _mensagens(recurso: str, limite: int, plano: str, seguinte: Optional[str]) -> Dict[str, str]:
    n = _NOMES.get(recurso, {"pt": recurso, "es": recurso, "en": recurso})
    nome = planos.PLANOS[plano].nome if plano in planos.PLANOS else plano
    prox = planos.PLANOS[seguinte].nome if seguinte in planos.PLANOS else None
    return {
        "pt": f"O plano {nome} inclui {limite} {n['pt']}. "
        + (
            f"Para mais, fale connosco sobre o plano {prox}."
            if prox
            else "Para mais, fale connosco."
        ),
        "es": f"El plan {nome} incluye {limite} {n['es']}. "
        + (
            f"Para más, hable con nosotros sobre el plan {prox}."
            if prox
            else "Para más, hable con nosotros."
        ),
        "en": f"The {nome} plan includes {limite} {n['en']}. "
        + (f"For more, talk to us about the {prox} plan." if prox else "For more, talk to us."),
    }


class LimiteDoPlanoError(PaymentRequiredError):
    """HTTP 402 com a frase pronta, nas três línguas, em `details.messages`."""

    def __init__(self, *, recurso: str, limite: int, atual: int, plano: str):
        seguinte = planos.PLANOS[plano].seguinte if plano in planos.PLANOS else None
        self.resource = recurso
        self.limit = limite
        self.current = atual
        self.tier = plano
        self.upgrade_hint = seguinte
        self.messages = _mensagens(recurso, limite, plano, seguinte)
        super().__init__(
            self.messages["pt"],
            upgrade_cta=(f"Plano {planos.PLANOS[seguinte].nome}" if seguinte else "Contacto"),
        )


class IntervaloDoPlanoError(PaymentRequiredError):
    """Um agente agendado mais depressa do que o plano permite."""

    def __init__(self, *, minimo: int, plano: str):
        self.resource = "min_agent_interval_minutes"
        self.limit = minimo
        self.tier = plano
        horas = minimo / 60
        quando = f"{int(horas)} h" if horas >= 1 else f"{minimo} min"
        nome = planos.PLANOS[plano].nome if plano in planos.PLANOS else plano
        self.messages = {
            "pt": f"No plano {nome}, um agente corre no máximo de {quando} em {quando}.",
            "es": f"En el plan {nome}, un agente se ejecuta como mucho cada {quando}.",
            "en": f"On the {nome} plan, an agent runs at most every {quando}.",
        }
        super().__init__(self.messages["pt"], upgrade_cta="")


# ── De quem é o pedido, e que plano tem ─────────────────────────────────


def _cliente() -> Optional[UUID]:
    """O id do cliente deste pedido, ou `None` no contexto da plataforma.

    O contexto por omissão é a PLATAFORMA (a semente `sky`, o modo de um só
    cliente, os testes): não há cliente a quem o plano se aplique. Um
    pedido de cliente mal resolvido cairia aqui — mas a defesa contra isso
    é o resolvedor, que já encaminha a base de dados: um pedido assim nem
    sequer vê os dados do cliente.
    """
    from src.core.tenant_context import current_tenant

    ctx = current_tenant()
    if ctx.is_default:
        return None
    return ctx.id


def _sessao_da_plataforma():
    from src.config.database import AsyncSessionLocal

    return AsyncSessionLocal()


async def _linha(
    s: AsyncSession, tenant_id: UUID, *, para_actualizar: bool = False
) -> TenantPlanLimits:
    """A linha do plano na plataforma. Criada a partir do registo se faltar."""
    q = select(TenantPlanLimits).where(TenantPlanLimits.tenant_id == tenant_id)
    if para_actualizar:
        q = q.with_for_update()
    row = (await s.execute(q)).scalar_one_or_none()
    if row is not None:
        return row
    from src.models.tenant import Tenant

    tier = (await s.execute(select(Tenant.tier).where(Tenant.id == tenant_id))).scalar_one_or_none()
    slug = planos.normalizar(tier)
    if slug is None:
        logger.error("planos: cliente %s sem plano conhecido (%r) — a recusar", tenant_id, tier)
        raise ServiceUnavailableError("Este cliente não tem um plano válido. Fale com a SkyFirst.")
    row = TenantPlanLimits(
        tenant_id=tenant_id,
        tier=slug,
        **planos.tectos(slug),
        max_users=None,
        queries_period_start=datetime.now(timezone.utc),
        last_threshold_alerted={},
    )
    s.add(row)
    await s.flush()
    return row


async def plano_do_cliente(tenant_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
    """`{plano, tectos…, perguntas_usadas}` — ou `None` em modo de um só cliente."""
    tid = tenant_id or _cliente()
    if tid is None:
        return None
    async with _sessao_da_plataforma() as s:
        row = await _linha(s, tid)
        await s.commit()
        d = {r: getattr(row, r) for r in planos.RECURSOS}
        d.update(
            plano=row.tier,
            personalizado=bool(row.personalizado),
            perguntas_usadas=row.current_queries_this_month,
        )
        return d


# ── O que se conta na base do cliente ───────────────────────────────────


async def _contar(db_cliente: AsyncSession, recurso: str) -> int:
    if recurso == "max_connections":
        from src.models.connection import DataConnection

        q = select(func.count()).select_from(DataConnection)
        if hasattr(DataConnection, "deleted_at"):
            q = q.where(DataConnection.deleted_at.is_(None))
        return int((await db_cliente.execute(q)).scalar() or 0)
    if recurso == "max_agents":
        from src.models.agent import Agent

        q = select(func.count()).select_from(Agent)
        if hasattr(Agent, "deleted_at"):
            q = q.where(Agent.deleted_at.is_(None))
        return int((await db_cliente.execute(q)).scalar() or 0)
    raise ValueError(recurso)


async def verificar_criacao(db_cliente: AsyncSession, recurso: str) -> None:
    """Antes de criar uma ligação ou um agente. 402 se o plano não deixa.

    O `pg_advisory_xact_lock` na base do cliente serializa duas criações
    em simultâneo: sem ele, com 0 de 1 usadas, as duas viam 0 e passavam.
    O lock dura até ao fim da transacção do pedido — a que faz o INSERT.
    """
    tid = _cliente()
    if tid is None:
        return
    async with _sessao_da_plataforma() as s:
        row = await _linha(s, tid)
        await s.commit()
        limite, plano = getattr(row, recurso), row.tier
    if limite is None:
        return
    if db_cliente.bind is not None and db_cliente.bind.dialect.name == "postgresql":
        await db_cliente.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"plano:{recurso}"}
        )
    atual = await _contar(db_cliente, recurso)
    if atual >= limite:
        raise LimiteDoPlanoError(recurso=recurso, limite=limite, atual=atual, plano=plano)


# ── Perguntas: reservar antes, devolver se falhar ──────────────────────


def _inicio_do_mes(agora: datetime) -> datetime:
    local = agora.astimezone(FUSO_DO_MES)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def reservar_pergunta(tenant_id: Optional[UUID] = None) -> bool:
    """Gasta uma pergunta do mês, ou 402. Devolve se houve reserva.

    Um só `UPDATE … WHERE n < max` — duas perguntas ao mesmo tempo com uma
    só de saldo não passam as duas. As corridas de agentes também passam
    por aqui: custam o mesmo que uma pergunta.
    """
    tid = tenant_id or _cliente()
    if tid is None:
        return False
    agora = datetime.now(timezone.utc)
    async with _sessao_da_plataforma() as s:
        row = await _linha(s, tid, para_actualizar=True)
        # A viragem do mês, à hora de cá.
        if row.queries_period_start is None or _inicio_do_mes(
            row.queries_period_start
        ) < _inicio_do_mes(agora):
            row.current_queries_this_month = 0
            row.queries_period_start = agora
            row.last_threshold_alerted = {}
        limite = row.max_queries_per_month
        if limite is not None and row.current_queries_this_month >= limite:
            atual, plano = row.current_queries_this_month, row.tier
            await s.rollback()
            raise LimiteDoPlanoError(
                recurso="max_queries_per_month", limite=limite, atual=atual, plano=plano
            )
        row.current_queries_this_month = (row.current_queries_this_month or 0) + 1
        await s.commit()
    return True


async def devolver_pergunta(tenant_id: Optional[UUID] = None) -> None:
    """Uma pergunta que falhou do nosso lado não gasta quota."""
    tid = tenant_id or _cliente()
    if tid is None:
        return
    async with _sessao_da_plataforma() as s:
        await s.execute(
            update(TenantPlanLimits)
            .where(
                TenantPlanLimits.tenant_id == tid, TenantPlanLimits.current_queries_this_month > 0
            )
            .values(current_queries_this_month=TenantPlanLimits.current_queries_this_month - 1)
        )
        await s.commit()


# ── Agentes: de quanto em quanto tempo ─────────────────────────────────

_UNIDADE_MIN = {"minute": 1, "hour": 60, "day": 1440, "week": 10080}
_FREQUENCIA_MIN = {
    "hourly": 60,
    "daily": 1440,
    "weekly": 10080,
    "monthly": 43200,
    "realtime": 1,
    "continuous": 1,
}


def intervalo_em_minutos(
    schedule: Optional[dict], frequency: Optional[str] = None
) -> Optional[int]:
    if (
        schedule
        and schedule.get("interval_value")
        and schedule.get("interval_unit") in _UNIDADE_MIN
    ):
        return int(schedule["interval_value"]) * _UNIDADE_MIN[schedule["interval_unit"]]
    if frequency:
        return _FREQUENCIA_MIN.get(str(frequency).lower())
    return None


async def verificar_intervalo(schedule: Optional[dict], frequency: Optional[str] = None) -> None:
    minutos = intervalo_em_minutos(schedule, frequency)
    if minutos is None:
        return
    tid = _cliente()
    if tid is None:
        return
    async with _sessao_da_plataforma() as s:
        row = await _linha(s, tid)
        await s.commit()
        minimo, plano = row.min_agent_interval_minutes, row.tier
    if minimo is not None and minutos < minimo:
        raise IntervaloDoPlanoError(minimo=minimo, plano=plano)


# ── Armazenamento ───────────────────────────────────────────────────────


async def armazenamento_usado_bytes(db_cliente: AsyncSession) -> int:
    """A base do cliente + os ficheiros carregados."""
    total = 0
    if db_cliente.bind is not None and db_cliente.bind.dialect.name == "postgresql":
        total += int(
            (await db_cliente.execute(text("SELECT pg_database_size(current_database())"))).scalar()
            or 0
        )
    try:
        total += int(
            (
                await db_cliente.execute(text("SELECT COALESCE(SUM(size), 0) FROM file_uploads"))
            ).scalar()
            or 0
        )
    except Exception:  # noqa: BLE001 — tabela ausente numa base antiga
        pass
    return total


async def verificar_armazenamento(db_cliente: AsyncSession, bytes_novos: int) -> None:
    tid = _cliente()
    if tid is None:
        return
    async with _sessao_da_plataforma() as s:
        row = await _linha(s, tid)
        await s.commit()
        limite_gb, plano = row.max_storage_gb, row.tier
    if limite_gb is None:
        return
    usado = await armazenamento_usado_bytes(db_cliente)
    if usado + max(0, bytes_novos) > limite_gb * 1024**3:
        raise LimiteDoPlanoError(
            recurso="max_storage_gb", limite=limite_gb, atual=int(usado / 1024**3), plano=plano
        )


# ── Só a Consola muda o plano ──────────────────────────────────────────


async def mudar_plano(
    s_plataforma: AsyncSession,
    tenant_id: UUID,
    plano_novo: str,
    tectos: Optional[Dict[str, Optional[int]]] = None,
) -> TenantPlanLimits:
    """Muda o plano (e, se vierem, os tectos à medida). Chamado SÓ pela Consola.

    Sem `tectos`, aplica os do plano e limpa o «personalizado». Com `tectos`,
    aplica-os por cima dos do plano e marca-o — é o «plano especial»:
    Starter com 2 ligações, por exemplo.
    """
    slug = planos.normalizar(plano_novo)
    if slug is None:
        raise ValueError(f"plano desconhecido: {plano_novo!r}")
    valores = planos.tectos(slug)
    personalizado = False
    for k, v in (tectos or {}).items():
        if k not in planos.RECURSOS:
            raise ValueError(f"tecto desconhecido: {k!r}")
        if v is not None and int(v) < 0:
            raise ValueError(f"{k} não pode ser negativo")
        if v != valores.get(k):
            personalizado = True
        valores[k] = v
    row = await _linha(s_plataforma, tenant_id, para_actualizar=True)
    row.tier = slug
    for k, v in valores.items():
        setattr(row, k, v)
    row.max_users = None
    row.personalizado = personalizado
    row.last_threshold_alerted = {}
    from src.models.tenant import Tenant

    await s_plataforma.execute(update(Tenant).where(Tenant.id == tenant_id).values(tier=slug))
    await s_plataforma.flush()
    return row


# ── O que NÃO conta ──────────────────────────────────────────────────────
#
# O aquecimento da cache semântica é trabalho nosso, não uma pergunta do
# cliente. Quem chama o sky-ai por conta própria marca-o com `sem_contar()`.

from contextlib import contextmanager  # noqa: E402
from contextvars import ContextVar  # noqa: E402

_NAO_CONTA: ContextVar[bool] = ContextVar("plano_nao_conta", default=False)


@contextmanager
def sem_contar():
    token = _NAO_CONTA.set(True)
    try:
        yield
    finally:
        _NAO_CONTA.reset(token)


async def reservar_pergunta_se_conta() -> bool:
    if _NAO_CONTA.get():
        return False
    return await reservar_pergunta()


async def verificar_saldo() -> None:
    """À entrada de uma rota de perguntas: 402 limpo se o mês já acabou.

    A reserva verdadeira é feita na porta do sky-ai (`http_client`); mas lá
    dentro o erro atravessa camadas que o transformam em «não consegui
    responder». Esta verificação, sem gastar nada, dá à pessoa a frase do
    plano em vez de uma avaria.
    """
    if _NAO_CONTA.get():
        return
    tid = _cliente()
    if tid is None:
        return
    agora = datetime.now(timezone.utc)
    async with _sessao_da_plataforma() as s:
        row = await _linha(s, tid)
        await s.commit()
        limite, usadas, plano, inicio = (
            row.max_queries_per_month,
            row.current_queries_this_month or 0,
            row.tier,
            row.queries_period_start,
        )
    if inicio is not None and _inicio_do_mes(inicio) < _inicio_do_mes(agora):
        usadas = 0  # o mês virou; a reserva repõe o contador
    if limite is not None and usadas >= limite:
        raise LimiteDoPlanoError(
            recurso="max_queries_per_month", limite=limite, atual=usadas, plano=plano
        )


# ── O que a Consola mostra ──────────────────────────────────────────────


async def uso_do_cliente(slug: str, tenant_id: UUID) -> Dict[str, Any]:
    """Contado agora, na base do cliente — o mesmo número que bloqueia.

    A Consola mostrava contadores guardados que ninguém actualizava (o
    «% de fontes» era calculado sobre utilizadores). Aqui conta-se o que o
    portão conta.
    """
    from src.api.deps import get_db_session_for_context
    from src.workers.por_cada_cliente import contexto_do_cliente

    uso: Dict[str, Any] = {"ligacoes": None, "agentes": None, "armazenamento_bytes": None}
    async with contexto_do_cliente(slug) as resolvido:
        if resolvido:
            gerador = get_db_session_for_context()
            db = await gerador.__anext__()
            try:
                uso["ligacoes"] = await _contar(db, "max_connections")
                uso["agentes"] = await _contar(db, "max_agents")
                uso["armazenamento_bytes"] = await armazenamento_usado_bytes(db)
            finally:
                await gerador.aclose()
    async with _sessao_da_plataforma() as s:
        row = await _linha(s, tenant_id)
        await s.commit()
        uso["perguntas_mes"] = row.current_queries_this_month or 0
    return uso


def excessos(plano_tectos: Dict[str, Optional[int]], uso: Dict[str, Any]) -> list:
    """O que o cliente já usa a mais do que estes tectos permitem."""
    pares = (
        ("max_connections", "ligacoes", 1),
        ("max_agents", "agentes", 1),
        ("max_storage_gb", "armazenamento_bytes", 1024**3),
    )
    fora = []
    for tecto, chave, escala in pares:
        limite, usado = plano_tectos.get(tecto), uso.get(chave)
        if limite is not None and usado is not None and usado > limite * escala:
            fora.append(
                {
                    "recurso": tecto,
                    "usado": usado if escala == 1 else round(usado / escala, 2),
                    "limite": limite,
                }
            )
    return fora
