"""Descoberta de cliente pelo domínio do email — login móvel.

Na web o cliente vem do sub-domínio. Uma app móvel fala com um host só,
portanto sem isto o backend não sabe em que base de dados procurar quem
está a tentar entrar — os utilizadores vivem em bases separadas por
cliente.

A regra que estes testes protegem, e que foi uma decisão de produto: o
ecrã de login **não pode ser um oráculo**. Domínio desconhecido, domínio
desactivado e cliente suspenso têm de ser indistinguíveis de uma
password errada. Se a mensagem mudasse, qualquer pessoa descobria a
lista de clientes da Sky escrevendo domínios até acertar.
"""

from __future__ import annotations

import uuid

import pytest

from src.models.tenant import Tenant
from src.models.tenant_domain import TenantDomain, domain_of_email, normalize_domain
from src.services.tenant_domain_service import TenantDomainService


async def _make_tenant(db, slug="gbtsolutions", active=True) -> Tenant:
    tenant = Tenant(
        id=uuid.uuid4(),
        slug=slug,
        display_name=slug.upper(),
        tier="starter",
        db_host="localhost",
        db_name="x",
        db_credentials_secret_arn="local",
        redis_host="localhost",
        redis_credentials_secret_arn="local",
        sso_provider="",
        sso_config={},
        auth_methods={"password": True},
        is_active=active,
    )
    db.add(tenant)
    await db.flush()
    return tenant


# ─── normalização ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("GBTSolutions.PT", "gbtsolutions.pt"),
        ("  gbt.pt  ", "gbt.pt"),
        # O ponto final absoluto é DNS válido e chegaria como um domínio
        # diferente do mesmo sítio.
        ("gbt.pt.", "gbt.pt"),
        ("", ""),
    ],
)
def test_normalizacao_de_dominio(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "email,expected",
    [
        ("lucas@GBTSolutions.pt", "gbtsolutions.pt"),
        # A parte local pode legalmente conter '@' entre aspas — parte-se
        # no último, não no primeiro.
        ('"odd@name"@gbt.pt', "gbt.pt"),
        ("sem-arroba", ""),
        ("", ""),
    ],
)
def test_dominio_extraido_do_email(email, expected):
    assert domain_of_email(email) == expected


# ─── resolução ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dominio_registado_resolve_o_cliente(db_session):
    tenant = await _make_tenant(db_session)
    await TenantDomainService.add_domain(db_session, tenant_id=tenant.id, domain="gbtsolutions.pt")
    await db_session.commit()

    found = await TenantDomainService.resolve_by_email(db_session, "lucas@gbtsolutions.pt")

    assert found is not None
    assert found.slug == "gbtsolutions"


@pytest.mark.asyncio
async def test_varios_dominios_para_o_mesmo_cliente(db_session):
    """Empresas fundem-se e mudam de marca sem migrar o email de toda a
    gente. Um domínio por cliente parece suficiente até ao primeiro
    cliente com dois."""
    tenant = await _make_tenant(db_session)
    for d in ("gbtsolutions.pt", "gbt.pt", "gbt-group.com"):
        await TenantDomainService.add_domain(db_session, tenant_id=tenant.id, domain=d)
    await db_session.commit()

    for email in ("a@gbtsolutions.pt", "b@gbt.pt", "c@gbt-group.com"):
        found = await TenantDomainService.resolve_by_email(db_session, email)
        assert found is not None and found.slug == "gbtsolutions", email


@pytest.mark.asyncio
async def test_dominio_desconhecido_devolve_none(db_session):
    """Silêncio, não erro. Quem chama traduz para as mesmas
    'credenciais inválidas' de uma password errada."""
    tenant = await _make_tenant(db_session)
    await TenantDomainService.add_domain(db_session, tenant_id=tenant.id, domain="gbt.pt")
    await db_session.commit()

    assert await TenantDomainService.resolve_by_email(db_session, "alguem@gmail.com") is None


@pytest.mark.asyncio
async def test_dominio_desactivado_devolve_none(db_session):
    tenant = await _make_tenant(db_session)
    await TenantDomainService.add_domain(
        db_session, tenant_id=tenant.id, domain="antigo.pt", is_active=False
    )
    await db_session.commit()

    assert await TenantDomainService.resolve_by_email(db_session, "x@antigo.pt") is None


@pytest.mark.asyncio
async def test_cliente_suspenso_devolve_none(db_session):
    """Suspender o cliente tem de fechar a porta do mobile também — não
    só a da web."""
    tenant = await _make_tenant(db_session, slug="suspenso", active=False)
    await TenantDomainService.add_domain(db_session, tenant_id=tenant.id, domain="suspenso.pt")
    await db_session.commit()

    assert await TenantDomainService.resolve_by_email(db_session, "x@suspenso.pt") is None


# ─── integridade ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_um_dominio_nao_pode_pertencer_a_dois_clientes(db_session):
    """Se pudesse, a resolução deixava de ser determinista e alguém
    entrava na base de dados da empresa errada."""
    a = await _make_tenant(db_session, slug="empresa-a")
    b = await _make_tenant(db_session, slug="empresa-b")
    await TenantDomainService.add_domain(db_session, tenant_id=a.id, domain="disputado.pt")
    await db_session.commit()

    with pytest.raises(ValueError, match="já pertence"):
        await TenantDomainService.add_domain(db_session, tenant_id=b.id, domain="disputado.pt")


@pytest.mark.asyncio
async def test_registar_o_mesmo_dominio_duas_vezes_e_idempotente(db_session):
    tenant = await _make_tenant(db_session)

    first = await TenantDomainService.add_domain(db_session, tenant_id=tenant.id, domain="GBT.pt")
    second = await TenantDomainService.add_domain(db_session, tenant_id=tenant.id, domain="gbt.pt ")
    await db_session.commit()

    assert first.id == second.id, "maiúsculas e espaços não podem criar uma segunda linha"
    assert (await TenantDomainService.list_for_tenant(db_session, tenant.id)).__len__() == 1


@pytest.mark.asyncio
async def test_dominio_e_guardado_em_forma_canonica(db_session):
    tenant = await _make_tenant(db_session)

    row = await TenantDomainService.add_domain(
        db_session, tenant_id=tenant.id, domain="  GBTSolutions.PT.  "
    )

    assert row.domain == "gbtsolutions.pt"


# ─── a decisão de produto ───────────────────────────────────────────


def test_nao_existe_indice_de_emails():
    """O Slack tem um, e é o que lhe permite o ecrã 'encontra os teus
    workspaces'. É também uma tabela de dados pessoais partilhada entre
    clientes. A Sky resolve por domínio precisamente para não a ter — um
    domínio diz 'a GBT é cliente', um email diria 'o Lucas trabalha na
    GBT'."""
    cols = {c.name for c in TenantDomain.__table__.columns}

    assert "email" not in cols
    assert "domain" in cols
