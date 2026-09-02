"""Seed an admin user inside a tenant DB.

Companion to ``scripts/seed_tenant_registry.py`` from PR #519. Whereas
``seed_tenant_registry`` writes the routing row, this script provisions
the first human who can log in: a row in the tenant DB's ``users``
table with ``role=admin``, ``email_verified=True``,
``has_completed_onboarding=True``, and a known password hash.

Designed to run inside the onboard-client workflow's migrate Job
(Model B) so a freshly minted tenant lands with a working account out
of the box. The workflow generates a random password, runs alembic,
runs this script, and posts the password back to the BE via the
report-phase webhook so the Console can surface it to the operator.

Env vars:

    DATABASE_URL              — required. A base do cliente; ou a da
                                PLATAFORMA, se se passar ``TENANT_SLUG``.
    TENANT_ADMIN_EMAIL        — required. e.g. ``lucas.ventura@gbtsolutions.pt``
    TENANT_ADMIN_PASSWORD     — required. plaintext (will be bcrypted)
    TENANT_SLUG               — opcional. Descobre a base dedicada do
                                cliente a partir do registo + Secrets
                                Manager. Quando presente, manda sobre o
                                ``DATABASE_URL``.
    TENANT_ADMIN_ROLE         — opcional. Por omissao ``super_admin``.
                                ``member`` para contas que so tem de ver.
                                Quando dado, **impoe-se tambem a contas
                                que ja existem**. Quando ausente, uma
                                conta existente fica com o papel que tem.
    TENANT_ADMIN_NAME         — opcional. defaults to "Admin"

Idempotent: an existing user with the same email is refreshed (new
password hash + role=admin) so re-running the migrate Job after a
schema bump doesn't leave dual accounts.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

# Pull in the model registry so the User mapper resolves cleanly.
import src.models  # noqa: F401, E402
from src.core.security import get_password_hash  # noqa: E402
from src.models.user import User  # noqa: E402


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"{name} env var required")
    return v


def _prepare_async_url(url: str) -> str:
    """Strip libpq ``sslmode`` and force ``+asyncpg`` so the same URL
    works for both Alembic (psycopg2) and SQLAlchemy/asyncpg without
    further surgery."""
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    parsed = urlparse(url)
    if not parsed.query:
        return url
    keep = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "sslmode"]
    return urlunparse(parsed._replace(query=urlencode(keep)))


async def _url_do_ambiente() -> str:
    """O URL da base onde escrever: dado a direito, ou descoberto do slug.

    ``TENANT_SLUG`` existe para quem so sabe o nome do cliente. Nesse caso
    ``DATABASE_URL`` tem de apontar a base da **plataforma** (e onde vive o
    registo) e o URL do cliente sai dali, ja com as credenciais do Secrets
    Manager.

    A ordem importa: se vier ``TENANT_SLUG``, ele manda. Deixar o
    ``DATABASE_URL`` ganhar seria pior de todas as formas — o script diria
    que semeou o cliente e teria escrito na plataforma, sem falhar.
    """
    slug = (os.environ.get("TENANT_SLUG") or "").strip()
    if not slug:
        return _prepare_async_url(_require("DATABASE_URL"))

    sys.path.insert(0, str(Path(__file__).parent))
    from _ligacao_ao_tenant import url_do_tenant

    url = await url_do_tenant(slug)
    print(f"  [..] cliente {slug!r}: base dedicada resolvida a partir do registo")
    return _prepare_async_url(url)


async def main() -> int:
    db_url = await _url_do_ambiente()
    email = _require("TENANT_ADMIN_EMAIL").strip().lower()
    password = _require("TENANT_ADMIN_PASSWORD")
    name = os.environ.get("TENANT_ADMIN_NAME") or "Admin"
    # `super_admin` continua a ser o valor por omissao: e para isso que este
    # script foi feito, e o onboarding depende dele. Mas nem toda a conta
    # semeada e um administrador — a do revisor das lojas tem de ver a app a
    # trabalhar e nao tem de poder administrar nada.
    papel_pedido = (os.environ.get("TENANT_ADMIN_ROLE") or "").strip()
    papel = papel_pedido or "super_admin"

    engine = create_async_engine(db_url, echo=False)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            existing = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            # First-user-of-a-tenant lands as ``super_admin`` — the tenant
            # founder. They get the full bypass (billing.manage,
            # tenant.delete, tenant.transfer_ownership) on top of the
            # admin powers. The 2026-06-03 rename moved this role from
            # ``owner`` (which collided with the Space/Crew/Page member
            # ``owner``) to ``super_admin``. See
            # ``skyfirst-role-taxonomy`` memory for the full table.
            if existing is not None:
                existing.password_hash = get_password_hash(password)
                # ── Quem pede um papel, leva esse papel. ──────────────
                #
                # Quem NAO pede fica como esta. A diferenca importa: sem
                # ela, uma conta criada antes fica com o papel de entao
                # para sempre, e a conta do revisor das lojas ficou
                # `super_admin` quando devia ser `member`.
                #
                # Mas impor `super_admin` a toda a gente por omissao
                # seria pior: este mesmo script corre no onboarding, e
                # promoveria em cada passagem qualquer conta que alguem
                # tivesse despromovido de proposito.
                if papel_pedido and existing.role != papel_pedido:
                    print(f"  [OK] papel de {email!r}: {existing.role} -> {papel_pedido}")
                    existing.role = papel_pedido
                elif not existing.role:
                    existing.role = papel
                existing.email_verified = True
                existing.has_completed_onboarding = True
                # ── Apagada nao e inexistente. ────────────────────────
                #
                # A procura acima nao filtra `deleted_at`, por isso uma
                # conta apagada em soft-delete e encontrada e leva password
                # nova — e continua apagada. O script diz "refreshed" e a
                # pessoa nao entra. Uma conta que este seed garante nao tem
                # estado nenhum em que ficar apagada seja o correcto.
                if existing.deleted_at is not None:
                    existing.deleted_at = None
                    print(f"  [OK] {email!r} estava apagada — reposta em servico")
                await session.commit()
                print(f"  [OK] tenant user {email!r} refreshed (role={existing.role})")
            else:
                user = User(
                    email=email,
                    password_hash=get_password_hash(password),
                    name=name,
                    role=papel,
                    email_verified=True,
                    has_completed_onboarding=True,
                )
                session.add(user)
                await session.commit()
                print(f"  [OK] tenant user {email!r} created (role={papel})")
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
