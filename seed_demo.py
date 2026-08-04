"""Seed a demo account + a few insights into the LOCAL backend DB.

Run:  venv/bin/python seed_demo.py
Prints the email / password / MFA secret / a live 6-digit code to log in with.
Idempotent: re-running refreshes the same demo user + its insights.

**Só corre contra uma base local.** Este script cria um utilizador com
``role="admin"``, password conhecida e — o que é pior — um segredo TOTP
fixo. Um segredo MFA conhecido não é MFA: quem tiver este ficheiro gera
códigos válidos para sempre. Contra staging ou produção seria uma porta
de administrador com chave publicada no repositório.

A guarda abaixo verifica o *host* da base de dados, não uma variável de
ambiente: `ENVIRONMENT` é fácil de deixar mal configurada, mas se o host
não for local então a base não é local, ponto. Para forçar (nunca em
produção), ``ALLOW_REMOTE_DEMO_SEED=1``.
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pyotp

from src.config.database import AsyncSessionLocal
from src.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
)
from src.models.agent import AgentFinding
from src.models.conversation import Conversation, Message
from src.models.page import Page
from src.models.connection import DataConnection
from src.models.space import Space, SpaceConnection, SpaceMember
from src.models.tenant import Tenant
from src.models.user import RefreshToken
from src.repositories.user import UserRepository
from src.services.mfa_service import MFAService

DEMO_TENANT_SLUG = "demo"

APP_DEV_SESSION = os.path.join(
    os.path.dirname(__file__), "..", "sky-mobile-app", "apps", "mobile", "src", "devSession.ts"
)

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "host.docker.internal", "postgres", "db")


def _refuse_unless_local() -> None:
    """Aborta se a base de dados não for local.

    Olha para o host real em vez de uma flag de ambiente: uma variável
    mal configurada é o modo de falha mais comum, e aqui o custo de
    falhar é um administrador com credenciais conhecidas numa base de
    cliente.
    """
    if os.environ.get("ALLOW_REMOTE_DEMO_SEED") == "1":
        print("⚠  ALLOW_REMOTE_DEMO_SEED=1 — a semear numa base NÃO local.")
        return

    url = os.environ.get("DATABASE_URL", "")
    host = os.environ.get("POSTGRES_HOST", "")
    if not url and not host:
        return  # sem configuração explícita, o default do settings é local

    # Extrair o host a sério, não procurar substrings. A primeira versão
    # desta guarda comparava por `in` e deixava passar
    # `sky-postgres-prod.eu-west-1.rds.amazonaws.com`, porque o nome
    # contém "postgres". Uma guarda enganada pelo nome do servidor é
    # pior do que nenhuma: dá confiança sem dar protecção.
    resolved = host
    if not resolved and url:
        from urllib.parse import urlsplit

        try:
            resolved = urlsplit(url).hostname or ""
        except ValueError:
            resolved = ""

    if resolved.lower() in _LOCAL_HOSTS:
        return

    print(
        "RECUSADO: a base de dados não parece local.\n"
        f"  Host resolvido: {resolved or '(desconhecido)'}\n\n"
        "Este script cria um utilizador admin com password conhecida e um\n"
        "segredo TOTP fixo. Contra staging ou produção isso é uma porta de\n"
        "administrador com a chave publicada no repositório.\n\n"
        "Se souberes mesmo o que estás a fazer: ALLOW_REMOTE_DEMO_SEED=1",
        file=sys.stderr,
    )
    sys.exit(2)


EMAIL = "demo@skyfirstlabs.com"
PASSWORD = "SkyDemo!2026"
DEMO_SPACE = uuid.UUID("11111111-1111-1111-1111-111111111111")
DEMO_PAGE = uuid.UUID("22222222-2222-2222-2222-222222222222")
# Local data-source the demo space is linked to, so /ai/chat/stream resolves a
# real connection (otherwise it returns no_data_source and the client falls back
# to a simulated answer). Defaults to the GBT local-mirror Postgres connection;
# override with DEMO_LOCAL_CONNECTION_ID for a different local dataset.
DEMO_LOCAL_CONNECTION_ID = os.getenv(
    "DEMO_LOCAL_CONNECTION_ID", "57de9594-3f50-4b8a-a04b-978f583f44fa"
)

# (title, days_ago, hours_ago, origin, duration_ms)
_CONVERSATIONS = [
    ("Why did North sales drop this week?", 0, 2, "text", None),
    ("Q2 hiring pace check", 0, 5, "text", None),
    ("Which clients are at risk of churn?", 1, 0, "voice", 47000),
    ("Marketing spend vs plan", 1, 3, "text", None),
    ("Inventory forecast for July", 6, 0, "voice", 82000),
]

_NOW = datetime.now(timezone.utc)
_INSIGHTS = [
    dict(
        kind="risk",
        level="high",
        title="North sales down 18% WoW",
        summary="Three lapsed clients explain most of the gap — together ~€24k of Q2 revenue.",
        series=[38, 41, 36, 33, 30, 27, 25, 22],
        tiles=[
            {"label": "Change", "value": "-18% vs avg"},
            {"label": "Lapsed clients", "value": "3"},
            {"label": "Q2 impact", "value": "€24,000"},
        ],
    ),
    dict(
        kind="opportunity",
        level="med",
        title="Pipeline velocity up 18% WoW, driven by 3 mid-market deals",
        summary="Stage-to-close time dropped from 34d to 28d.",
        series=[34, 33, 32, 31, 30, 29, 28, 28],
        tiles=[
            {"label": "Velocity", "value": "+18%"},
            {"label": "Cycle time", "value": "28 days"},
            {"label": "Deals", "value": "3"},
        ],
    ),
    dict(
        kind="insight",
        level="low",
        title="LinkedIn campaign CAC down 22% — room to scale budget",
        summary="Cost per acquisition fell for the second week running.",
        series=[120, 116, 110, 104, 99, 96, 94, 93],
        tiles=[
            {"label": "CAC", "value": "-22%"},
            {"label": "Current CAC", "value": "€93"},
            {"label": "Trend", "value": "2 weeks"},
        ],
    ),
    dict(
        kind="risk",
        level="med",
        title="Customer NPS dropped 22 pts after the v4.2 rollout",
        summary="Support tickets tripled; renewal conversation in 6 weeks.",
        series=[52, 50, 48, 44, 40, 33, 31, 30],
        tiles=[
            {"label": "NPS", "value": "-22 pts"},
            {"label": "Tickets", "value": "3x"},
            {"label": "ARR at risk", "value": "€48k"},
        ],
    ),
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # A demo tenant with password login enabled, so the app can do REAL
        # email/password + MFA (the default workspace disables password). The
        # app sends X-Tenant-Slug: demo so the login gate resolves this row.
        tenant = (
            await db.execute(Tenant.__table__.select().where(Tenant.slug == DEMO_TENANT_SLUG))
        ).first()
        if tenant is None:
            db.add(
                Tenant(
                    slug=DEMO_TENANT_SLUG,
                    display_name="Demo Workspace",
                    tier="starter",
                    db_host="localhost",
                    db_name="ai_saas_db",
                    db_credentials_secret_arn="local-dev",
                    redis_host="localhost",
                    redis_credentials_secret_arn="local-dev",
                    sso_provider="",
                    sso_config={},
                    auth_methods={"password": True, "google": True, "azure": False, "okta": False},
                    is_active=True,
                )
            )
            await db.commit()

        # Register the demo email domain → demo tenant, so the app logs in the
        # Teams way: email + password only, the domain identifies the workspace
        # (no X-Tenant-Slug needed). Idempotent; unique per domain.
        from src.models.tenant_domain import TenantDomain, domain_of_email

        tenant_row = (
            await db.execute(Tenant.__table__.select().where(Tenant.slug == DEMO_TENANT_SLUG))
        ).first()
        demo_domain = domain_of_email(EMAIL)
        if tenant_row is not None and demo_domain:
            has_domain = (
                await db.execute(
                    TenantDomain.__table__.select().where(TenantDomain.domain == demo_domain)
                )
            ).first()
            if has_domain is None:
                db.add(TenantDomain(domain=demo_domain, tenant_id=tenant_row.id, is_active=True))
                await db.commit()
            print(f"Tenant domain for Teams login: {demo_domain} → {DEMO_TENANT_SLUG}")

        users = UserRepository(db)

        user = await users.get_by_email(EMAIL)
        if user is None:
            user = await users.create(
                email=EMAIL,
                password_hash=get_password_hash(PASSWORD),
                name="Demo Operator",
                role="admin",
            )
        else:
            user.password_hash = get_password_hash(PASSWORD)
        await db.commit()
        await db.refresh(user)

        # Enrol MFA with a secret we control, so we can print a working code.
        mfa = MFAService(db)
        # Fixed secret so you add it to an authenticator ONCE and it survives
        # re-seeds (generate_enrollment would rotate it every run).
        secret = "SKYMOBILEDEMO234"
        await mfa.verify_enrollment(user, secret=secret, code=pyotp.TOTP(secret).now())
        await db.commit()

        # The space (real Postgres enforces the FK) + membership so the feed
        # is scoped to a space we control.
        space = await db.get(Space, DEMO_SPACE)
        if space is None:
            db.add(Space(id=DEMO_SPACE, name="Demo Space", created_by=user.id))
            await db.commit()

        exists = await db.execute(
            SpaceMember.__table__.select().where(
                (SpaceMember.user_id == user.id) & (SpaceMember.space_id == DEMO_SPACE)
            )
        )
        if exists.first() is None:
            db.add(SpaceMember(user_id=user.id, space_id=DEMO_SPACE, role="member"))
        await db.commit()

        # Link the demo space to a real local data connection so the AI chat
        # (and voice) resolve a data source and stream REAL answers. Without
        # this, /ai/chat/stream emits `no_data_source` and the mobile client
        # falls back to a clearly-labelled simulated answer. Idempotent; skips
        # with a warning if the connection isn't present in this environment.
        try:
            conn_id = uuid.UUID(str(DEMO_LOCAL_CONNECTION_ID))
        except (ValueError, TypeError):
            conn_id = None
        conn = await db.get(DataConnection, conn_id) if conn_id else None
        if conn is not None:
            link = await db.execute(
                SpaceConnection.__table__.select().where(
                    (SpaceConnection.space_id == DEMO_SPACE)
                    & (SpaceConnection.connection_id == conn.id)
                )
            )
            if link.first() is None:
                db.add(SpaceConnection(space_id=DEMO_SPACE, connection_id=conn.id))
                await db.commit()
            print(f"Linked demo space to data connection: {conn.name} ({conn.id})")
        else:
            print(
                "WARNING: DEMO_LOCAL_CONNECTION_ID "
                f"({DEMO_LOCAL_CONNECTION_ID}) not found — the AI chat will fall "
                "back to a simulated answer until a data connection is linked."
            )

        # Refresh the demo insights (delete + re-insert for idempotency).
        await db.execute(AgentFinding.__table__.delete().where(AgentFinding.space_id == DEMO_SPACE))
        for i, spec in enumerate(_INSIGHTS):
            db.add(
                AgentFinding(
                    agent_id=None,
                    source="scan",
                    space_id=DEMO_SPACE,
                    agent_name="Autonomous scan",
                    type=spec["kind"],
                    severity=spec["level"],
                    title=spec["title"],
                    description=spec["summary"],
                    series=[
                        {"t": (_NOW - timedelta(days=len(spec["series"]) - j)).isoformat(), "v": v}
                        for j, v in enumerate(spec["series"])
                    ],
                    stat_tiles=spec["tiles"],
                    viz_kind="line",
                    created_at=_NOW - timedelta(hours=i),
                )
            )
        await db.commit()

        # ── History (BE-04): a page + conversations (voice/text, various days) ──
        if await db.get(Page, DEMO_PAGE) is None:
            db.add(
                Page(
                    id=DEMO_PAGE,
                    name="Sky Chats",
                    type="personal",
                    color="#FAB721",
                    owner_id=user.id,
                )
            )
            await db.commit()

        rows = (
            await db.execute(
                Conversation.__table__.select().where(Conversation.page_id == DEMO_PAGE)
            )
        ).fetchall()
        old_ids = [r.id for r in rows]
        if old_ids:
            await db.execute(Message.__table__.delete().where(Message.conversation_id.in_(old_ids)))
            await db.execute(
                Conversation.__table__.delete().where(Conversation.page_id == DEMO_PAGE)
            )
            await db.commit()

        for title, days, hours, origin, dur in _CONVERSATIONS:
            when = _NOW - timedelta(days=days, hours=hours)
            conv = Conversation(
                page_id=DEMO_PAGE,
                created_by=user.id,
                title=title,
                created_at=when,
                updated_at=when,
            )
            db.add(conv)
            await db.flush()
            db.add(
                Message(
                    conversation_id=conv.id,
                    role="user",
                    content=title,
                    origin=origin,
                    duration_ms=dur,
                    created_at=when,
                )
            )
        await db.commit()

        # Mint a ready-to-use session so the app has a one-click "Dev login"
        # (the backend disables password login by default + forces MFA — too
        # many production gates for a localhost demo).
        claims = {"sub": str(user.id), "email": user.email, "role": user.role}
        access = create_access_token(claims)
        refresh = create_refresh_token(claims, client_type="mobile")
        db.add(
            RefreshToken(
                user_id=user.id,
                token=refresh,
                expires_at=_NOW + timedelta(days=45),
                family_id=uuid.uuid4(),
            )
        )
        await db.commit()

        with open(os.path.normpath(APP_DEV_SESSION), "w") as fh:
            fh.write(
                "// Auto-generated by seed_demo.py — a ready session for the\n"
                "// localhost 'Dev login' button. Re-run the seed if it expires.\n"
                f'export const DEV_SESSION = {{\n  access: "{access}",\n'
                f'  refresh: "{refresh}",\n  pageId: "{DEMO_PAGE}",\n}};\n'
            )

        print("\n" + "=" * 54)
        print("  DEMO ACCOUNT READY")
        print("=" * 54)
        print(f"  One-click: use the 'Dev login (localhost)' button in the app")
        print("  ----------------------------------------------------")
        print(f"  Or the real flow — Email:  {EMAIL}")
        print(f"                     Password: {PASSWORD}")
        print(f"                     MFA secret: {secret}")
        print(f"                     MFA code now: {pyotp.TOTP(secret).now()}")
        print(f"  Insights seeded: {len(_INSIGHTS)}")
        print("=" * 54 + "\n")


if __name__ == "__main__":
    _refuse_unless_local()
    asyncio.run(main())
