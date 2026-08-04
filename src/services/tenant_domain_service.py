"""Resolução de cliente a partir do domínio do email.

O passo que falta para o login móvel funcionar como o Teams: a pessoa
escreve email e password, e o backend descobre em que base de dados
procurá-la a partir do domínio.

Regra de silêncio, e é deliberada: **um domínio desconhecido devolve
``None``, nunca um erro distinto**. Quem chama traduz isso para as
mesmas "credenciais inválidas" que uma password errada produziria. Se a
resposta distinguisse "esse domínio não existe" de "essa password está
errada", o ecrã de login passava a ser um oráculo — qualquer um
descobria quais as empresas que são clientes da Sky, escrevendo domínios
até a mensagem mudar.

A consulta vai à base de **registo** (a partilhada), não à do cliente:
tem de responder antes de sabermos qual é o cliente, que é exactamente o
problema a resolver.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tenant import Tenant
from src.models.tenant_domain import TenantDomain, domain_of_email, normalize_domain

logger = logging.getLogger(__name__)


class TenantDomainService:
    """Descoberta de cliente por domínio (home realm discovery)."""

    @staticmethod
    async def resolve_by_domain(session: AsyncSession, domain: str) -> Optional[Tenant]:
        """O cliente dono deste domínio, ou ``None``.

        ``None`` cobre três casos que quem chama **não** deve
        distinguir: domínio não registado, domínio desactivado, e
        cliente suspenso. Para quem está a sondar de fora, os três têm
        de ser indistinguíveis de uma password errada.
        """
        needle = normalize_domain(domain)
        if not needle:
            return None

        row = (
            await session.execute(
                select(Tenant)
                .join(TenantDomain, TenantDomain.tenant_id == Tenant.id)
                .where(TenantDomain.domain == needle)
                .where(TenantDomain.is_active.is_(True))
                .where(Tenant.is_active.is_(True))
            )
        ).scalar_one_or_none()

        if row is None:
            # `info`, não `warning`: um domínio desconhecido é o caso
            # normal de quem se engana a escrever, não um incidente.
            logger.info("tenant_domain_unresolved", extra={"domain": needle})
        return row

    @staticmethod
    async def resolve_by_email(session: AsyncSession, email: str) -> Optional[Tenant]:
        """O cliente a que este email pertence, pelo seu domínio."""
        return await TenantDomainService.resolve_by_domain(session, domain_of_email(email))

    @staticmethod
    async def add_domain(
        session: AsyncSession, *, tenant_id, domain: str, is_active: bool = True
    ) -> TenantDomain:
        """Regista um domínio a um cliente. Idempotente por domínio.

        Se o domínio já pertencer a **outro** cliente, levanta. Mover um
        domínio entre clientes tem de ser um acto explícito — feito por
        engano, manda os funcionários de uma empresa para a base de
        dados de outra.
        """
        needle = normalize_domain(domain)
        if not needle:
            raise ValueError("domínio vazio")

        existing = (
            await session.execute(select(TenantDomain).where(TenantDomain.domain == needle))
        ).scalar_one_or_none()

        if existing is not None:
            if str(existing.tenant_id) != str(tenant_id):
                raise ValueError(
                    f"o domínio {needle!r} já pertence a outro cliente "
                    f"({existing.tenant_id}) — mover exige remover primeiro"
                )
            existing.is_active = is_active
            await session.flush()
            return existing

        row = TenantDomain(domain=needle, tenant_id=tenant_id, is_active=is_active)
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def list_for_tenant(session: AsyncSession, tenant_id) -> list[TenantDomain]:
        return list(
            (
                await session.execute(
                    select(TenantDomain)
                    .where(TenantDomain.tenant_id == tenant_id)
                    .order_by(TenantDomain.domain)
                )
            )
            .scalars()
            .all()
        )


__all__ = ["TenantDomainService"]
