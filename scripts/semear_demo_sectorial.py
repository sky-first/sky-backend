#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semeia uma demonstração sectorial na base de um cliente.

    DATABASE_URL=<base do cliente> \\
    DEMO_PG_HOST=... DEMO_PG_USER=... DEMO_PG_PASSWORD=... \\
    python scripts/semear_demo_sectorial.py transportes \\
        --dono lucas.ventura@skyfirstlabs.com \\
        --confirmar-base tenant_skyfirstlabs

Sem `--aplicar` não escreve nada: corre todas as consultas contra a base
sintética, diz o que ia criar, e desfaz. É onde se apanha um SQL partido
sem deixar meio projecto na base de um cliente.

── `--confirmar-base` não é cerimónia ──────────────────────────────

Os semeadores deste repositório já escreveram na base errada: o
`envFrom` do Job injecta o `DATABASE_URL` da plataforma, e uma
sobreposição que deixe de pegar faz o script correr com sucesso
aparente contra o plano de controlo. O
`14-job-ligacoes-demo-num-cliente-prd.yaml` leva um `case` a confirmar
o destino pela mesma razão.

Confirmar o destino é a diferença entre falhar e estragar.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

if not os.environ.get("DATABASE_URL"):
    print("Falta DATABASE_URL (a base do cliente).", file=sys.stderr)
    raise SystemExit(1)

from scripts.demo_sectorial import alimentacion, restauracion, transportes  # noqa: E402
from scripts.demo_sectorial.motor import (  # noqa: E402
    SementeiraRecusada,
    semear,
    sincronizar_metadados,
)
from src.config.database import AsyncSessionLocal  # noqa: E402


async def _sessao():
    """A base onde se semeia: a do cliente, se `TENANT_SLUG` vier.

    Sem o slug usa-se o `DATABASE_URL` tal e qual, que é o caminho de
    quem corre isto à mão contra uma base local.

    Com o slug, o `DATABASE_URL` tem de apontar à base da **plataforma**
    — é lá que vive o registo — e a base dedicada do cliente é resolvida
    a partir dele. É o mesmo caminho do `seed_demo_knowledge.py`, e
    existe pela mesma razão: um Job não pode trazer o URL da base de
    cada cliente no manifesto.
    """
    slug = (os.environ.get("TENANT_SLUG") or "").strip()
    if not slug:
        return AsyncSessionLocal(), os.environ["DATABASE_URL"]

    sys.path.insert(0, str(Path(__file__).parent))
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from _ligacao_ao_tenant import url_do_tenant

    url = await url_do_tenant(slug)
    print(f"cliente {slug!r}: base dedicada resolvida a partir do registo")
    motor = create_async_engine(url, pool_pre_ping=True)
    return async_sessionmaker(motor, expire_on_commit=False)(), url


SECTORES = {
    "alimentacion": alimentacion.SECTOR,
    "restauracion": restauracion.SECTOR,
    "transportes": transportes.SECTOR,
}


async def principal(args) -> int:
    sessao, url = await _sessao()
    if args.confirmar_base not in url:
        print(
            f"ABORTADO: --confirmar-base {args.confirmar_base!r} não aparece no "
            "DATABASE_URL.\nSemear na base errada não dá erro — fica lá, parece "
            "certo, e ninguém dá por isso.",
            file=sys.stderr,
        )
        return 1

    sector = SECTORES[args.sector]
    print(f"sector: {sector.nome_do_projecto}")
    print(f"base:   …{url[-40:]}")
    print(f"modo:   {'APLICAR' if args.aplicar else 'ensaio (nada é gravado)'}")
    print("-" * 60)

    async with sessao as db:
        try:
            resumo = await semear(db, sector, email_do_dono=args.dono)
        except SementeiraRecusada as e:
            await db.rollback()
            print(f"\nRECUSADO: {e}", file=sys.stderr)
            return 1

        if args.aplicar:
            await db.commit()
            print("\ngravado.")
        else:
            await db.rollback()
            print("\nensaio — nada foi gravado. Repetir com --aplicar.")

    # ── os metadados, depois do commit ──────────────────────────────
    #
    # Sem este passo o projecto abre com os painéis cheios e não responde
    # a nada. A conversa e os agentes dão «The AI service rejected the
    # request», que é como o backend traduz o 404 do `sky-ai` quando a
    # ligação não tem metadados — uma mensagem que manda procurar um
    # defeito no serviço de IA, que está bom.
    #
    # Ver a nota longa em `motor.sincronizar_metadados`.
    #
    # Só com `--aplicar`: num ensaio as ligações foram desfeitas e não há
    # nada para introspeccionar.
    #
    # O `url` é o mesmo que o semeador usou — a base do CLIENTE quando
    # vem `TENANT_SLUG`. Sem o passar, a sincronização abria a base da
    # plataforma e dava «Connection not found» nas três ligações.
    ids = resumo.pop("ligacoes_criadas", [])
    if args.aplicar:
        print(f"\na sincronizar metadados de {len(ids)} ligações…")
        feitas = await sincronizar_metadados(ids, url, args.dono)
        resumo["metadados"] = f"{feitas}/{len(ids)} ligações"
        if feitas < len(ids):
            print(
                "AVISO: ficaram ligações sem metadados. Os painéis funcionam "
                "na mesma, porque os números estão gravados — mas a conversa "
                "e os agentes vão recusar as perguntas dessas ligações.",
                file=sys.stderr,
            )

    print("-" * 60)
    for k, v in resumo.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("sector", choices=sorted(SECTORES))
    ap.add_argument("--dono", default=None, help="email do dono; omitir usa o 1.º utilizador")
    ap.add_argument(
        "--confirmar-base", required=True, help="pedaço que tem de estar no DATABASE_URL"
    )
    ap.add_argument("--aplicar", action="store_true")
    raise SystemExit(asyncio.run(principal(ap.parse_args())))
