"""Tarefa diária do RGPD — anonimização após remoção e retenção.

Corre no ``sky-beat`` uma vez por dia, **em cada cliente e na plataforma**
(``por_cada_cliente``): os utilizadores e a auditoria de cada cliente vivem
na base dele. Em cada base:

1. anonimiza quem foi removido há mais de ``ANONIMIZACAO_APOS_REMOCAO_DIAS``;
2. apaga auditoria com mais de ``RETENCAO_AUDITORIA_DIAS`` e refresh tokens
   expirados há mais de ``RETENCAO_SESSOES_EXPIRADAS_DIAS``;
3. pede ao sky-ai a retenção dos registos dele nessa mesma base
   (``query_audit_log``, ``prompt_security_audit``, ``security_alerts``).

Com ``RGPD_LIMPEZA_DRY_RUN`` (ligado por omissão) só conta. O resultado e os
logs levam contagens e o ``slug`` do cliente — nunca dados de pessoas.

Para correr à mão, dentro de um pod do backend::

    celery -A src.workers.celery_app call \\
        src.workers.rgpd_worker.manutencao_rgpd_diaria --kwargs '{"dry_run": true}'
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.config.settings import settings
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _uma_base(slug: str, dry_run: bool) -> Dict[str, Any]:
    """As três passagens numa base (a do contexto actual)."""
    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.core.tenant_context import current_tenant
    from src.services.rgpd_service import aplicar_retencao, anonimizar_removidos

    saida: Dict[str, Any] = {}
    falhas: list = []
    async with tenant_connection_manager.session_for(current_tenant()) as db:
        a = await anonimizar_removidos(
            db, dias=int(settings.ANONIMIZACAO_APOS_REMOCAO_DIAS), dry_run=dry_run
        )
        saida.update(a.contagens)
        falhas += a.falhas
        r = await aplicar_retencao(
            db,
            dias_auditoria=int(settings.RETENCAO_AUDITORIA_DIAS),
            dias_sessoes_expiradas=int(settings.RETENCAO_SESSOES_EXPIRADAS_DIAS),
            dry_run=dry_run,
        )
        saida.update(r.contagens)
        falhas += r.falhas

    try:
        from src.ai.http_client import AIServiceHTTPClient

        ai = await AIServiceHTTPClient().aplicar_retencao_auditoria(
            dry_run=dry_run, tenant_slug=slug
        )
        # O sky-ai diz em que base correu. Se não for a pedida (slug que não
        # resolveu e caiu na plataforma), as contagens não são deste cliente.
        base_ai = (ai or {}).get("base")
        if base_ai and base_ai != slug:
            falhas.append("sky_ai:base_errada")
        else:
            for k, v in ((ai or {}).get("contagens") or {}).items():
                saida[f"ai_{k}"] = int(v or 0)
            falhas += [f"sky_ai:{f}" for f in (ai or {}).get("falhas") or []]
    except Exception as exc:  # noqa: BLE001 — o sky-ai em baixo não trava o resto
        falhas.append(f"sky_ai:{type(exc).__name__}")

    saida["falhas"] = falhas
    return saida


@celery_app.task(name="src.workers.rgpd_worker.manutencao_rgpd_diaria")
def manutencao_rgpd_diaria(dry_run: Optional[bool] = None) -> Dict[str, Any]:
    """Uma passagem por cada cliente. ``dry_run=None`` segue o ambiente."""
    from src.workers.laco_do_celery import correr
    from src.workers.por_cada_cliente import por_cada_cliente

    modo_dry = settings.RGPD_LIMPEZA_DRY_RUN if dry_run is None else bool(dry_run)
    por_base: Dict[str, Dict[str, Any]] = {}

    async def _passagem(slug: str):
        r = await _uma_base(slug, modo_dry)
        por_base[slug] = r
        logger.info("rgpd[%s] dry_run=%s %s", slug, modo_dry, r)
        anon = int(r.get("utilizadores_anonimizados", r.get("utilizadores_por_anonimizar", 0)))
        apag = sum(int(v) for k, v in r.items() if k.endswith(("_apagados", "_a_apagar")))
        return anon, apag

    anon, apag = correr(por_cada_cliente(_passagem, nome="rgpd"))
    return {
        "dry_run": modo_dry,
        "utilizadores": anon,
        "registos": apag,
        "bases": por_base,
    }
