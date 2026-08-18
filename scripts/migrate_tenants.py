"""Aplica as migrações a **todas** as bases de clientes, não só à da plataforma.

Porque existe
-------------
O Job de migração corria ``alembic upgrade head`` contra a base da plataforma e
mais nada. As bases dos clientes ficavam para trás **a cada deploy que trouxesse
uma migração**, e ninguém dava por isso até alguma coisa rebentar.

O efeito não é benigno. Assim que o código novo entra, uma tabela que ganhou
coluna passa a ser lida com essa coluna no SELECT, e o cliente recebe:

    asyncpg.exceptions.UndefinedColumnError:
    column data_connections.nao_cruzavel does not exist

Foi exactamente isso a 18/08/2026: a plataforma estava em
``cross_project_20260818`` e as bases dos clientes duas e três revisões atrás
(`skyfirstlabs` em ``message_finding_20260814``, `sandbox` em
``device_registry_20260805``). O mesmo defeito já tinha aparecido antes, com o
chat a devolver 500 por falta de ``conversations.session_id`` — e nessa altura
escreveu-se um runbook manual (``RUNBOOK_migrate_tenant_db.md``) em vez de
automatizar. Isto é a automatização.

Falha alto, de propósito
------------------------
Se a migração de um cliente falhar, o script sai com erro e o *hook* trava o
deploy. É o comportamento certo: **não se serve código cujo esquema não existe
em todo o lado**. Um cliente esquecido é pior do que um deploy adiado — o deploy
adiado vê-se, o cliente esquecido só se vê quando alguém se queixa.

Uso::

    python scripts/migrate_tenants.py           # todos os clientes activos
    python scripts/migrate_tenants.py --dry-run # só diz o que faria
    python scripts/migrate_tenants.py --slug x  # um só
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from typing import List, Tuple
from urllib.parse import quote_plus, unquote, urlparse

from sqlalchemy import select


async def _clientes(slug: str | None) -> List[Tuple[str, str]]:
    """(slug, url) de cada cliente activo com base dedicada."""
    from src.config.database import AsyncSessionLocal
    from src.models.tenant import Tenant

    async with AsyncSessionLocal() as db:
        consulta = select(Tenant).where(Tenant.is_active.is_(True))
        if slug:
            consulta = consulta.where(Tenant.slug == slug)
        linhas = list((await db.execute(consulta)).scalars().all())

    # A base da plataforma já foi migrada pelo passo anterior do hook. O `sky`
    # aponta para ela: é a semente reservada do registo, não um cliente. Sem
    # esta guarda, o script corria o alembic uma segunda vez contra a mesma
    # base — inofensivo hoje (já está no head), mas é o género de coisa que
    # confunde quem lê os logs à procura de um problema real.
    plataforma = (os.environ.get("DATABASE_URL") or "").rsplit("/", 1)[-1].split("?")[0]

    saida: List[Tuple[str, str]] = []
    for row in linhas:
        if not row.db_host or not row.db_name:
            print(f"  {row.slug}: sem base dedicada, ignorado")
            continue
        if row.db_name == plataforma:
            print(f"  {row.slug}: é a base da plataforma, já migrada")
            continue
        saida.append((row.slug, _url(row)))
    return saida


def _url(row) -> str:
    import boto3  # type: ignore[import-untyped]

    host = row.db_host
    port = getattr(row, "db_port", None) or 5432
    arn = row.db_credentials_secret_arn

    blob = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"])
    if "username" in blob and "password" in blob:
        user, pw = blob["username"], blob["password"]
    else:
        parsed = urlparse(blob["url"])
        user, pw = unquote(parsed.username or ""), unquote(parsed.password or "")
    return f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(pw)}@{host}:{port}/{row.db_name}"


def _migrar(slug: str, url: str) -> bool:
    """Corre o alembic contra a base deste cliente.

    Em subprocesso, e não em processo, porque o alembic lê o URL do ambiente e
    guarda estado global — partilhar processo entre clientes é como se pede uma
    migração aplicada à base errada.
    """
    ambiente = dict(os.environ, DATABASE_URL=url)
    print(f"  {slug}: a migrar…", flush=True)
    r = subprocess.run(
        ["alembic", "upgrade", "head"],
        env=ambiente,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        # O URL traz credenciais — o que se mostra é o erro, nunca o ambiente.
        print(f"  {slug}: FALHOU\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}", file=sys.stderr)
        return False
    ultimas = [l for l in r.stdout.splitlines() if "Running upgrade" in l]
    print(f"  {slug}: ok ({len(ultimas)} migrações aplicadas)")
    for l in ultimas:
        print(f"      {l.split('Running upgrade ')[-1]}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slug", help="Migrar só este cliente.")
    p.add_argument("--dry-run", action="store_true", help="Listar sem migrar.")
    args = p.parse_args()

    clientes = asyncio.run(_clientes(args.slug))
    if not clientes:
        print("Nenhum cliente com base dedicada. Nada a fazer.")
        return 0

    print(f"Clientes a migrar: {[s for s, _ in clientes]}")
    if args.dry_run:
        return 0

    falhados = [slug for slug, url in clientes if not _migrar(slug, url)]
    if falhados:
        print(
            f"\nFALHOU em {falhados}. O deploy trava aqui de propósito: não se "
            f"serve código cujo esquema não existe em todo o lado.",
            file=sys.stderr,
        )
        return 1
    print(f"\n{len(clientes)} clientes na mesma revisão da plataforma.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
