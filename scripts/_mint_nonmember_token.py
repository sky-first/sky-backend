"""One-off e2e helper: create a throwaway NON-MEMBER user in a tenant DB
and mint their access token, to verify the Option B content gate denies
non-members. Prints ONLY the token on the last line.

Run inside a sky-be pod (settings = platform; tenant URL resolved from the
registry). Usage: python _mint_nonmember_token.py [slug]
"""

from __future__ import annotations

import asyncio
import sys
import uuid


async def _resolve_url(slug: str) -> str:
    import json
    from urllib.parse import quote_plus, unquote, urlparse

    from sqlalchemy import select

    from src.config.database import AsyncSessionLocal
    from src.models.tenant import Tenant

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one()
        host, port, name, arn = (
            row.db_host,
            getattr(row, "db_port", None) or 5432,
            row.db_name,
            row.db_credentials_secret_arn,
        )
    import boto3  # type: ignore[import-untyped]

    blob = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"])
    if "username" in blob and "password" in blob:
        user, pw = blob["username"], blob["password"]
    else:
        parsed = urlparse(blob["url"])
        user, pw = unquote(parsed.username or ""), unquote(parsed.password or "")
    return f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(pw)}@{host}:{port}/{name}"


async def _main() -> None:
    slug = sys.argv[1] if len(sys.argv) > 1 else "gbtsolutions"
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.config.database import prepare_async_db_url
    from src.core.security import create_access_token, get_password_hash
    from src.repositories.user import UserRepository

    url = await _resolve_url(slug)
    cleaned, ssl_kwargs = prepare_async_db_url(url)
    eng = create_async_engine(cleaned, echo=False, connect_args=ssl_kwargs)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as db:
        repo = UserRepository(db)
        email = f"nonmember-{uuid.uuid4().hex[:8]}@e2e.local"
        u = await repo.create(
            email=email,
            password_hash=get_password_hash("x"),
            name="E2E Non-Member",
            role="member",  # plain member, NOT added to any crew/space
        )
        await db.commit()
        token = create_access_token({"sub": str(u.id), "email": u.email, "role": u.role})
    await eng.dispose()
    print(f"user_id={u.id} email={email}", file=sys.stderr)
    print(token)


if __name__ == "__main__":
    asyncio.run(_main())
