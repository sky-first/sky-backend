"""Converge um cliente para o que a Consola pediu. Idempotente.

Uma só função, ``convergir_cliente(slug)``, serve para marcar, desmarcar,
reconciliar e para o hook de projecto novo. Lê o estado **desejado** da base
da plataforma (``fontes_sistema_cliente``), e:

1. ``sky_world`` (``world_admin``): papéis ``wsrc_*`` com os SELECT certos,
   papel ``wt_<slug>``, e membros = fontes desejadas (GRANT/REVOKE).
2. Base do cliente, dentro de ``contexto_do_cliente(slug)``: utilizador de
   sistema, ligação «Dados públicos», em todos os projectos, metadados
   filtrados por privilégio, ``space_tables``, limpeza do índice e da cache
   semântica quando sai alguma coisa.
3. Discover do sky-ai em cada projecto, com ``X-Tenant-Slug`` EXPLÍCITO (S1).
4. Estado na plataforma: ``pronta`` / ``erro`` / ``desligada``.

**Dois operadores ao mesmo tempo (S17).** Cada PUT da Consola muda o
``pedido_id`` da linha. No fim, a tarefa relê as linhas: só escreve o estado
nas que não mudaram, e se alguma mudou corre outra vez (até 3 voltas). A
reconciliação de hora a hora apanha o resto.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.models.fonte_sistema import FonteSistema, FonteSistemaCliente
from src.models.tenant import Tenant
from src.services.fontes_sistema import credenciais, ligacao_gerida
from src.services.fontes_sistema.catalogo import (
    TABELA_FRESCURA,
    FonteInvalidaError,
    papel_do_cliente,
    tabelas_da_fonte,
    validar_para_ativar,
)
from src.services.fontes_sistema.mundo import Mundo

logger = logging.getLogger(__name__)

MAX_VOLTAS = 3

_RE_SEGREDO = re.compile(r"(password|pwd|secret|token)=\S+|://[^@\s]+@", re.I)


class ClienteNaoResolvidoError(RuntimeError):
    """O slug não resolve para um cliente com base própria. Falha alto (S1)."""


def _sem_segredos(texto: str) -> str:
    return _RE_SEGREDO.sub("***", texto or "")[:300]


def _erro(exc: BaseException, passo: str) -> dict:
    return {
        "mensagem": _sem_segredos(f"{type(exc).__name__}: {exc}"),
        "passo": passo,
        "quando": datetime.now(timezone.utc).isoformat(),
    }


def _sessao_plataforma() -> AsyncSession:
    from src.config.database import AsyncSessionLocal

    return AsyncSessionLocal()


def _sessao_do_cliente() -> AsyncSession:
    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.core.tenant_context import current_tenant

    return tenant_connection_manager.session_for(current_tenant())


async def _ler_pedido(s: AsyncSession, slug: str):
    tenant = (await s.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if tenant is None:
        raise ClienteNaoResolvidoError(f"cliente desconhecido: {slug!r}")
    linhas = (
        await s.execute(
            select(FonteSistemaCliente, FonteSistema)
            .join(FonteSistema, FonteSistema.id == FonteSistemaCliente.fonte_id)
            .where(FonteSistemaCliente.tenant_id == tenant.id)
        )
    ).all()
    return tenant, [(r[0], r[1]) for r in linhas]


async def convergir_cliente(
    slug: str,
    *,
    mundo: Optional[Callable[[], Any]] = None,
    sessao_plataforma: Optional[Callable[[], AsyncSession]] = None,
    sessao_do_cliente: Optional[Callable[[], AsyncSession]] = None,
    contexto: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """Converge ``slug``. Os parâmetros opcionais existem para os testes."""
    if not settings.FONTES_SISTEMA_ENABLED:
        return {"slug": slug, "estado": "funcionalidade_desligada"}
    papel_do_cliente(slug)  # valida o slug antes de qualquer SQL

    from src.workers.por_cada_cliente import contexto_do_cliente

    abrir_mundo = mundo or Mundo
    abrir_plataforma = sessao_plataforma or _sessao_plataforma
    abrir_cliente = sessao_do_cliente or _sessao_do_cliente
    entrar = contexto or contexto_do_cliente

    resumo: Dict[str, Any] = {"slug": slug, "voltas": 0}
    for volta in range(1, MAX_VOLTAS + 1):
        resumo["voltas"] = volta
        mudou = await _uma_volta(slug, abrir_mundo, abrir_plataforma, abrir_cliente, entrar, resumo)
        if not mudou:
            break
    return resumo


async def _uma_volta(slug, abrir_mundo, abrir_plataforma, abrir_cliente, entrar, resumo) -> bool:
    # ── 0. O que se pede ────────────────────────────────────────────────
    async with abrir_plataforma() as s:
        tenant, linhas = await _ler_pedido(s, slug)
    retrato = {row.fonte_id: row.pedido_id for row, _ in linhas}
    erros: Dict[str, dict] = {}
    desejadas: List[FonteSistema] = []
    for row, fonte in linhas:
        if not row.ativa:
            continue
        try:
            validar_para_ativar(fonte)
        except FonteInvalidaError as exc:
            erros[fonte.id] = _erro(exc, "catalogo")
            continue
        desejadas.append(fonte)
    ids_desejados = {f.id for f in desejadas}
    tabelas_por_fonte = {f.id: tabelas_da_fonte(f) for f in desejadas}
    alvo: Set[str] = set().union(*tabelas_por_fonte.values()) if desejadas else set()

    erro_geral: Optional[dict] = None
    revogadas: Set[str] = set()
    tabelas_finais: List[str] = []
    spaces: list = []
    passo = "sky_world"
    try:
        # ── 1. sky_world ────────────────────────────────────────────────
        async with abrir_mundo() as m:
            for f in desejadas:
                falta = await m.garantir_papel_da_fonte(f.id, tabelas_por_fonte[f.id])
                if falta:
                    erros[f.id] = {
                        "mensagem": "tabelas em falta em sky_world: " + ", ".join(falta),
                        "passo": "sky_world",
                        "quando": datetime.now(timezone.utc).isoformat(),
                    }
            papel_existe = await m.papel_existe(papel_do_cliente(slug))
            if desejadas or papel_existe:
                if desejadas:
                    await m.garantir_papel_do_cliente(slug)
                atuais = await m.fontes_do_cliente(slug) if papel_existe or desejadas else set()
                for fid in sorted(ids_desejados - atuais):
                    await m.conceder(fid, slug)
                for fid in sorted(atuais - ids_desejados):
                    await m.revogar(fid, slug)
                    revogadas.add(fid)

        # ── 2. Base do cliente ──────────────────────────────────────────
        passo = "base_do_cliente"
        async with entrar(slug) as resolveu:
            if not resolveu:
                raise ClienteNaoResolvidoError(
                    f"{slug!r} não resolveu para um cliente com base própria"
                )
            ligacao_id = None
            async with abrir_cliente() as db:
                if desejadas:
                    dono = await ligacao_gerida.garantir_utilizador_de_sistema(db)
                    lig = await ligacao_gerida.garantir_ligacao(db, slug, dono)
                    spaces = await ligacao_gerida.projetos(db)
                    await ligacao_gerida.garantir_nos_projetos(db, lig.id, spaces)
                    await db.commit()
                    passo = "metadados"
                    visiveis = set(await ligacao_gerida.sincronizar_metadados(db, lig))
                    tabelas_finais = sorted((alvo | {TABELA_FRESCURA}) & visiveis)
                    for f in desejadas:
                        faltam = [t for t in tabelas_por_fonte[f.id] if t not in visiveis]
                        if faltam and f.id not in erros:
                            erros[f.id] = {
                                "mensagem": "sem acesso às tabelas: " + ", ".join(faltam),
                                "passo": "metadados",
                                "quando": datetime.now(timezone.utc).isoformat(),
                            }
                    removidas = await ligacao_gerida.acertar_tabelas(
                        db, lig.id, spaces, tabelas_finais
                    )
                    ligacao_id = lig.id
                else:
                    lig = await ligacao_gerida.ligacao_do_sistema(db)
                    removidas = set()
                    if lig is not None:
                        spaces = await ligacao_gerida.projetos(db)
                        removidas = await ligacao_gerida.acertar_tabelas(db, lig.id, spaces, [])
                        await ligacao_gerida.desligar(db, lig)
                    spaces = []
                await ligacao_gerida.limpar_indice(db, lig.id if lig else None, removidas)
                if removidas or revogadas:
                    resumo["cache_apagada"] = await ligacao_gerida.invalidar_cache_semantica(db)
                await db.commit()

            # ── 3. Discover, com o cliente EXPLÍCITO ─────────────────────
            passo = "discover"
            falhas: Dict[str, str] = {}
            if ligacao_id is not None and spaces and tabelas_finais:
                falhas = await ligacao_gerida.descobrir(ligacao_id, spaces, slug, tabelas_finais)
            if falhas:
                resumo["discover_falhou"] = falhas
                for f in desejadas:
                    erros.setdefault(
                        f.id,
                        {
                            "mensagem": f"discover falhou em {len(falhas)} projecto(s)",
                            "passo": "discover",
                            "quando": datetime.now(timezone.utc).isoformat(),
                        },
                    )
        resumo["tabelas"] = tabelas_finais
        resumo["projetos"] = len(spaces)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fontes_sistema[%s]: falhou em %s: %s", slug, passo, type(exc).__name__)
        erro_geral = _erro(exc, passo)
        resumo["erro"] = erro_geral

    # ── 4. Estado, só nas linhas que ninguém mexeu entretanto ──────────
    agora = datetime.now(timezone.utc)
    mudou = False
    async with abrir_plataforma() as s:
        _, linhas = await _ler_pedido(s, slug)
        for row, fonte in linhas:
            if retrato.get(row.fonte_id) != row.pedido_id:
                mudou = True
                continue
            if row.ativa:
                e = erros.get(row.fonte_id) or erro_geral
                if e:
                    row.estado, row.erro = "erro", e
                else:
                    if row.estado != "pronta":
                        row.pronta_em = agora
                    row.estado, row.erro = "pronta", None
            else:
                if erro_geral:
                    row.estado, row.erro = "erro", erro_geral
                elif row.estado != "desligada":
                    row.estado, row.erro = "desligada", None
        await s.commit()
    resumo["estados"] = {
        r.fonte_id: r.estado for r, _ in linhas if retrato.get(r.fonte_id) == r.pedido_id
    }
    return mudou


async def remover_cliente(
    slug: str,
    *,
    mundo: Optional[Callable[[], Any]] = None,
    sessao_plataforma: Optional[Callable[[], AsyncSession]] = None,
) -> None:
    """Destruição do cliente (S20): papel, segredo e linhas de activação."""
    papel_do_cliente(slug)
    async with (mundo or Mundo)() as m:
        await m.remover_cliente(slug)
    credenciais.apagar(credenciais.ref_do_cliente(slug))
    async with (sessao_plataforma or _sessao_plataforma)() as s:
        tenant = (await s.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
        if tenant is not None:
            await s.execute(
                delete(FonteSistemaCliente).where(FonteSistemaCliente.tenant_id == tenant.id)
            )
            await s.commit()


async def clientes_com_fontes(s: AsyncSession) -> List[str]:
    linhas = (
        await s.execute(
            select(Tenant.slug)
            .join(FonteSistemaCliente, FonteSistemaCliente.tenant_id == Tenant.id)
            .where(Tenant.is_active.is_(True))
            .distinct()
        )
    ).all()
    return sorted(r[0] for r in linhas)


async def papeis_orfaos(
    *,
    mundo: Optional[Callable[[], Any]] = None,
    sessao_plataforma: Optional[Callable[[], AsyncSession]] = None,
) -> List[str]:
    """Papéis ``wt_*`` sem cliente vivo (S20): credencial órfã com acesso a dados."""
    async with (sessao_plataforma or _sessao_plataforma)() as s:
        slugs = (
            (await s.execute(select(Tenant.slug).where(Tenant.is_active.is_(True)))).scalars().all()
        )
    esperados = set()
    for sl in slugs:
        try:
            esperados.add(papel_do_cliente(sl))
        except FonteInvalidaError:
            continue
    async with (mundo or Mundo)() as m:
        existentes = await m.papeis_de_clientes()
    return sorted(existentes - esperados)
