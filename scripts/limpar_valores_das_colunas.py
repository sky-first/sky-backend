"""Tira «Possible values: …» dos metadados guardados, em todas as bases.

Até 13/10/2026 o conector Postgres escrevia valores reais das colunas na
descrição (``connection_metadata.tables``). O conector já não o faz; isto limpa
o que ficou — na base da plataforma e na de cada cliente (via
``tenant_connection_manager``) — e pede ao sky-ai nova descoberta das ligações
afectadas, para refazer ``table_metadata`` e os embeddings sem os valores.

Idempotente: a segunda corrida não encontra nada e não pede nada.

Depois disto, correr ``scripts/limpar_dados_do_cliente.py --apply`` no sky-ai
(apanha ligações sem espaço, a cache semântica e os checkpoints).

Uso (num pod do sky-be, com ``DATABASE_URL`` da plataforma e IRSA)::

    python scripts/limpar_valores_das_colunas.py              # só conta
    python scripts/limpar_valores_das_colunas.py --apply      # limpa + descoberta
    python scripts/limpar_valores_das_colunas.py --apply --slug sandbox
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def _uma_base(nome: str, sessao, *, a_serio: bool, slug, ai_client) -> None:
    from src.services.metadados_sem_valores import (
        limpar_metadados_da_base,
        pedir_nova_descoberta,
    )

    async with sessao as db:
        afectadas = await limpar_metadados_da_base(db, a_serio=a_serio)
        total = sum(n for _, n in afectadas)
        print(f"  {nome}: {len(afectadas)} ligações, {total} descrições com valores")
        if not a_serio or not afectadas:
            return
        pedidos, sem_espaco = await pedir_nova_descoberta(
            db,
            [cid for cid, _ in afectadas],
            ai_client=ai_client,
            tenant_slug=slug,
        )
        print(f"  {nome}: {pedidos} descobertas pedidas ao sky-ai")
        if sem_espaco:
            print(f"  {nome}: sem espaço (o script do sky-ai trata): {sem_espaco}")


async def principal() -> int:
    from sqlalchemy import select

    from src.ai.http_client import AIServiceHTTPClient
    from src.api.middleware.tenant_resolver import _row_to_context
    from src.config.database import AsyncSessionLocal, engine
    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.models.tenant import Tenant

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="limpar a sério")
    parser.add_argument("--slug", help="só este cliente (e não a plataforma)")
    args = parser.parse_args()
    a_serio = args.apply
    print("A LIMPAR" if a_serio else "DRY-RUN (só conta; --apply para limpar)")

    ai_client = AIServiceHTTPClient()
    falharam: list[str] = []

    if not args.slug:
        try:
            await _uma_base(
                "plataforma",
                AsyncSessionLocal(),
                a_serio=a_serio,
                slug=None,
                ai_client=ai_client,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  plataforma: FALHOU — {type(e).__name__}: {str(e)[:200]}")
            falharam.append("plataforma")

    async with AsyncSessionLocal() as s:
        clientes = (
            (await s.execute(select(Tenant).where(Tenant.is_active.is_(True)))).scalars().all()
        )
    for row in clientes:
        if args.slug and row.slug != args.slug:
            continue
        if not row.db_host or not row.db_name:
            print(f"  {row.slug}: sem base dedicada, ignorado")
            continue
        # O `sky` aponta para a base da plataforma (semente reservada, e o
        # segredo dele nem é legível): já foi tratada acima.
        if row.db_name == engine.url.database:
            print(f"  {row.slug}: é a base da plataforma, já tratada")
            continue
        ctx = _row_to_context(row)
        if ctx.is_default:
            continue
        try:
            await _uma_base(
                row.slug,
                tenant_connection_manager.session_for(ctx),
                a_serio=a_serio,
                slug=row.slug,
                ai_client=ai_client,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  {row.slug}: FALHOU — {type(e).__name__}: {str(e)[:200]}")
            falharam.append(row.slug)

    await tenant_connection_manager.dispose_all()
    if falharam:
        print(f"\nFalharam: {falharam}")
        return 1
    print("\nFeito." if a_serio else "\nNada mudou (dry-run).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
