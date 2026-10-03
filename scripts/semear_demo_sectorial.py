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

from scripts.demo_sectorial import alimentacion, transportes  # noqa: E402
from scripts.demo_sectorial.motor import SementeiraRecusada, semear  # noqa: E402
from src.config.database import AsyncSessionLocal  # noqa: E402

SECTORES = {
    "alimentacion": alimentacion.SECTOR,
    "transportes": transportes.SECTOR,
}


async def principal(args) -> int:
    url = os.environ["DATABASE_URL"]
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

    async with AsyncSessionLocal() as db:
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

    print("-" * 60)
    for k, v in resumo.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("sector", choices=sorted(SECTORES))
    ap.add_argument("--dono", default=None, help="email do dono; omitir usa o 1.º utilizador")
    ap.add_argument("--confirmar-base", required=True, help="pedaço que tem de estar no DATABASE_URL")
    ap.add_argument("--aplicar", action="store_true")
    raise SystemExit(asyncio.run(principal(ap.parse_args())))
