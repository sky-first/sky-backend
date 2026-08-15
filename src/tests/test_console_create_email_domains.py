"""O create do Console regista os domínios de email do cliente.

Sem isto, um cliente novo nasce inacessível: a tabela `tenant_domains`
fica vazia, o login não consegue descobrir a que cliente pertence quem
está a entrar, e cai na base da plataforma. Estava a ser preenchida à
mão, uma linha de SQL por venda.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.schemas.internal_console import CreateTenantRequest


def _payload(**extra):
    # Os campos do plano de dados são obrigatórios quando as definições
    # do ambiente não trazem defeito — no ambiente de teste não trazem.
    # No Console real o operador deixa-os vazios e são derivados do slug.
    base = dict(
        slug="teamblue",
        display_name="TeamBlue",
        tier="starter",
        db_host="rds.exemplo",
        db_name="tenant_teamblue",
        db_credentials_secret_arn="arn:aws:secretsmanager:eu-west-1:1:secret:x",
        redis_host="redis.exemplo",
        redis_credentials_secret_arn="arn:aws:secretsmanager:eu-west-1:1:secret:y",
    )
    base.update(extra)
    return CreateTenantRequest(**base)


def test_email_domains_e_opcional():
    """Um cliente sem domínios continua a poder ser criado.

    Há casos legítimos — provisionar primeiro, declarar os domínios
    depois — e não queremos partir quem já chama esta API.
    """
    assert _payload().email_domains is None


def test_email_domains_aceita_varios():
    """Uma empresa pode ter mais do que um domínio.

    `teamblue.com` e `teamblue.pt` são a mesma gente.
    """
    p = _payload(email_domains=["teamblue.com", "teamblue.pt"])
    assert p.email_domains == ["teamblue.com", "teamblue.pt"]


class _DbFalso:
    """Sessão suficiente para o create_tenant correr sem Postgres."""

    def __init__(self):
        self.adicionados = []

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        return None

    async def refresh(self, obj):
        return None

    async def rollback(self):
        return None

    async def execute(self, *a, **kw):
        # O create faz consultas de apoio (contagens, leituras de apoio ao
        # detalhe devolvido). Nenhuma delas interessa a este teste: o que
        # se verifica é quais os domínios que chegam ao serviço.
        class _Res:
            def scalar_one_or_none(self):
                return None

            def scalar(self):
                return 0

            def scalars(self):
                return self

            def all(self):
                return []

            def first(self):
                return None

        return _Res()


async def test_create_regista_cada_dominio():
    """Cada domínio indicado tem de acabar em `tenant_domains`.

    Exercita mesmo o `create_tenant` — não basta afirmar o payload, que
    passaria na mesma se alguém apagasse o ciclo do serviço.
    """
    from src.services import console_service

    chamadas = []

    async def _add_domain(session, *, tenant_id, domain, is_active=True):
        chamadas.append(domain)

    db = _DbFalso()
    # O create termina lendo o detalhe do cliente da base; o duplo não
    # sabe montá-lo e não é isso que está em causa aqui.
    with patch(
        "src.services.tenant_domain_service.TenantDomainService.add_domain",
        new=AsyncMock(side_effect=_add_domain),
    ), patch.object(console_service, "get_tenant_detail", new=AsyncMock(return_value=object())):
        await console_service.create_tenant(
            db,
            _payload(email_domains=["teamblue.com", "teamblue.pt"]),
            actor_email="lucas@skyfirstlabs.com",
        )

    assert chamadas == ["teamblue.com", "teamblue.pt"]


async def test_create_sem_dominios_nao_chama_o_servico():
    """Sem domínios não se toca na tabela — nem com uma linha vazia."""
    from src.services import console_service

    add = AsyncMock()
    db = _DbFalso()
    with patch(
        "src.services.tenant_domain_service.TenantDomainService.add_domain", new=add
    ), patch.object(console_service, "get_tenant_detail", new=AsyncMock(return_value=object())):
        await console_service.create_tenant(
            db, _payload(), actor_email="lucas@skyfirstlabs.com"
        )

    add.assert_not_awaited()


async def test_dominio_de_outro_cliente_faz_o_create_falhar():
    """Mover um domínio entre clientes tem de ser explícito.

    Registar `ikea.com` no cliente errado manda os funcionários da IKEA
    para a base de dados de outra empresa. `add_domain` levanta, e o
    create deixa o erro subir em vez de o engolir.
    """
    from src.services import console_service

    db = _DbFalso()
    with patch(
        "src.services.tenant_domain_service.TenantDomainService.add_domain",
        new=AsyncMock(
            side_effect=ValueError("o domínio 'ikea.com' já pertence a outro cliente")
        ),
    ), patch.object(console_service, "get_tenant_detail", new=AsyncMock(return_value=object())):
        with pytest.raises(ValueError, match="já pertence a outro cliente"):
            await console_service.create_tenant(
                db,
                _payload(slug="falsa-ikea", email_domains=["ikea.com"]),
                actor_email="atacante@exemplo.com",
            )
