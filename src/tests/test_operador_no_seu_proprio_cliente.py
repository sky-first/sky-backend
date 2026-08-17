"""Um operador da Sky dentro do workspace da própria Sky não é "suporte".

O que se partiu, e quando:

O consentimento JIT existe para o caso em que alguém da Sky entra no workspace
de **um cliente** — break-glass, com registo e com prazo. A isenção estava
escrita como "o contexto por omissão", o que era equivalente enquanto a Sky não
fosse cliente de si própria.

A 16/08/2026 a equipa passou a ter workspace próprio. A partir desse dia,
qualquer pessoa com `@skyfirstlabs.com` entrava e **o primeiro pedido morria**:

    Sky support access requires an active JIT consent session

São operadores (o flag é posto automaticamente a quem entra com esse email), o
cliente resolvido não é o por omissão, e não há sessão de suporte — nem faria
sentido haver, é a casa deles.

A regra certa é a que o docstring já dizia: casa é o cliente dono do domínio do
email do operador. Estes testes fixam as duas metades — a que deixa entrar e,
mais importante, a que **continua a barrar**.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.services import rbac_service


def _operador(email="lucas.ventura@skyfirstlabs.com"):
    return SimpleNamespace(id=uuid4(), email=email, is_sky_operator=True)


def _contexto(tenant_id, *, default=False):
    return SimpleNamespace(id=tenant_id, slug="qualquer", is_default=default)


@pytest.mark.asyncio
async def test_em_casa_nao_precisa_de_consentimento():
    casa = uuid4()
    with patch(
        "src.services.tenant_domain_service.TenantDomainService.resolve_by_domain",
        AsyncMock(return_value=SimpleNamespace(id=casa)),
    ):
        assert await rbac_service._e_o_cliente_de_casa(_operador(), _contexto(casa)) is True


@pytest.mark.asyncio
async def test_no_workspace_de_um_cliente_continua_a_precisar():
    """A metade que não pode enfraquecer."""
    casa, cliente = uuid4(), uuid4()
    with patch(
        "src.services.tenant_domain_service.TenantDomainService.resolve_by_domain",
        AsyncMock(return_value=SimpleNamespace(id=casa)),
    ):
        assert await rbac_service._e_o_cliente_de_casa(_operador(), _contexto(cliente)) is False


@pytest.mark.asyncio
async def test_dominio_desconhecido_falha_fechado():
    with patch(
        "src.services.tenant_domain_service.TenantDomainService.resolve_by_domain",
        AsyncMock(return_value=None),
    ):
        assert await rbac_service._e_o_cliente_de_casa(_operador(), _contexto(uuid4())) is False


@pytest.mark.asyncio
async def test_registo_indisponivel_falha_fechado():
    """Se o registo de domínios não responde, barra-se. Nunca ao contrário."""
    with patch(
        "src.services.tenant_domain_service.TenantDomainService.resolve_by_domain",
        AsyncMock(side_effect=RuntimeError("registo em baixo")),
    ):
        assert await rbac_service._e_o_cliente_de_casa(_operador(), _contexto(uuid4())) is False


@pytest.mark.asyncio
async def test_email_sem_dominio_falha_fechado():
    assert await rbac_service._e_o_cliente_de_casa(_operador("semarroba"), _contexto(uuid4())) is False


@pytest.mark.asyncio
async def test_quem_nao_e_operador_nunca_passa_pelo_portao():
    normal = SimpleNamespace(id=uuid4(), email="alguem@gbt.pt", is_sky_operator=False)
    assert await rbac_service._is_sky_operator_without_jit(normal, AsyncMock()) is False
