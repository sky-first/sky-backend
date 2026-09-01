"""Descobre a ligação à base dedicada de um cliente, a partir do slug.

O registo dos clientes vive na base da plataforma; as credenciais de cada
base dedicada vivem no AWS Secrets Manager, e o registo guarda só o ARN.
Montar o URL exige os dois — e é exactamente o género de regra que não
pode existir em duas versões.

O ``migrate_tenants.py`` já a tinha. Este módulo é a mesma lógica, num
sítio só, para o seed da conta do revisor a poder usar sem a copiar.

Precisa de:

- ``DATABASE_URL`` a apontar à base da **plataforma** (é lá que está o
  registo);
- permissão IAM para ler o segredo do cliente. Em produção vem do IRSA
  ``sky-be-prd-platform-tenants-access``; sem ela o ``get_secret_value``
  rebenta com ``AccessDeniedException``, que é o sintoma de faltar o
  ``serviceAccountName`` no Job e não de o cliente não existir.
"""

from __future__ import annotations

import json
from urllib.parse import quote_plus, unquote, urlparse


class ClienteSemBaseDedicada(RuntimeError):
    """O cliente existe no registo mas não tem base própria."""


class ClienteDesconhecido(RuntimeError):
    """Não há cliente activo com esse slug."""


def url_a_partir_do_registo(row) -> str:
    """O URL asyncpg de um cliente, dada a sua linha do registo.

    Aceita as duas formas em que o segredo aparece: ``{username,
    password}`` (o que o provisionamento escreve) e ``{url}`` (o que
    algumas bases mais antigas têm). A diferença não é histórica só por
    acaso — assumir uma delas parte metade dos clientes.
    """
    import boto3  # type: ignore[import-untyped]

    host = row.db_host
    port = getattr(row, "db_port", None) or 5432
    arn = row.db_credentials_secret_arn

    blob = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"])
    if "username" in blob and "password" in blob:
        utilizador, palavra = blob["username"], blob["password"]
    else:
        partido = urlparse(blob["url"])
        utilizador = unquote(partido.username or "")
        palavra = unquote(partido.password or "")

    return (
        f"postgresql+asyncpg://{quote_plus(utilizador)}:{quote_plus(palavra)}"
        f"@{host}:{port}/{row.db_name}"
    )


async def url_do_tenant(slug: str) -> str:
    """O URL da base dedicada do cliente ``slug``.

    Levanta ``ClienteDesconhecido`` ou ``ClienteSemBaseDedicada`` em vez
    de devolver um URL que aponta para a plataforma. **Esse engano é o
    perigoso:** um seed que julga estar a escrever na base de um cliente
    e escreve na da plataforma não falha — cria o utilizador no sítio
    errado, e só se descobre quando alguém não consegue entrar.
    """
    from sqlalchemy import select

    from src.config.database import AsyncSessionLocal
    from src.models.tenant import Tenant

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True)))
        ).scalar_one_or_none()

    if row is None:
        raise ClienteDesconhecido(f"não há cliente activo com o slug {slug!r}")
    if not row.db_host or not row.db_name:
        raise ClienteSemBaseDedicada(
            f"o cliente {slug!r} não tem base dedicada (db_host/db_name por preencher)"
        )

    return url_a_partir_do_registo(row)
