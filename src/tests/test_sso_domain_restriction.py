"""O `sso_domain_restriction` passa a restringir alguma coisa.

Era gravado pelo Console e **nunca lido** — pior do que não existir, porque
quem o preenchia ficava a acreditar que tinha fechado o cliente a um domínio.

Vai à frente da regra do "já existe", de propósito: se alguém foi provisionado
por engano com um endereço de fora, a existência da conta não deve chegar. O
domínio é a regra da casa, não uma propriedade do utilizador.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.exceptions import ForbiddenError
from src.services.auth0_service import Auth0Service


def _service(restriction, existing_user=None) -> Auth0Service:
    svc = Auth0Service.__new__(Auth0Service)
    svc.db = MagicMock()

    class _Row:
        def first(self):
            return (restriction,)

    svc.db.execute = AsyncMock(return_value=_Row())
    svc.user_repo = MagicMock()
    svc.user_repo.get_by_email = AsyncMock(return_value=existing_user)
    return svc


def _tenant(monkeypatch, slug="skyfirstlabs"):
    monkeypatch.setattr(
        "src.core.tenant_context.current_tenant", lambda: MagicMock(slug=slug)
    )


@pytest.mark.asyncio
async def test_o_dominio_certo_passa(monkeypatch):
    _tenant(monkeypatch)
    svc = _service("skyfirstlabs.com", existing_user=MagicMock())
    await svc.authorise_sso_identity(
        email="lucas.ventura@skyfirstlabs.com", email_verified=True, provider="google"
    )


@pytest.mark.asyncio
async def test_um_dominio_de_fora_e_recusado(monkeypatch):
    _tenant(monkeypatch)
    svc = _service("skyfirstlabs.com", existing_user=MagicMock())
    with pytest.raises(ForbiddenError):
        await svc.authorise_sso_identity(
            email="alguem@gmail.com", email_verified=True, provider="google"
        )


@pytest.mark.asyncio
async def test_a_conta_existir_nao_chega(monkeypatch):
    """Alguém provisionado por engano com um endereço de fora continua
    trancado — que é o ponto de a regra ser da casa e não da pessoa."""
    _tenant(monkeypatch)
    svc = _service("skyfirstlabs.com", existing_user=MagicMock())
    with pytest.raises(ForbiddenError):
        await svc.authorise_sso_identity(
            email="antigo@outraempresa.com", email_verified=True, provider="google"
        )


@pytest.mark.asyncio
async def test_sufixo_parecido_nao_engana(monkeypatch):
    """`skyfirstlabs.com` não pode deixar passar `naoskyfirstlabs.com`.

    É o mesmo erro de sufixo que o `_is_sky_team_email` já evita comparando
    com o "@" à frente.
    """
    _tenant(monkeypatch)
    svc = _service("skyfirstlabs.com", existing_user=MagicMock())
    with pytest.raises(ForbiddenError):
        await svc.authorise_sso_identity(
            email="intruso@naoskyfirstlabs.com", email_verified=True, provider="google"
        )


@pytest.mark.asyncio
async def test_varios_dominios_separados_por_virgula(monkeypatch):
    """Uma empresa com .com e .pt é o caso normal, não a excepção."""
    _tenant(monkeypatch)
    svc = _service("empresa.com, empresa.pt", existing_user=MagicMock())
    for addr in ("ana@empresa.com", "ana@empresa.pt"):
        await svc.authorise_sso_identity(
            email=addr, email_verified=True, provider="google"
        )
    with pytest.raises(ForbiddenError):
        await svc.authorise_sso_identity(
            email="ana@outra.com", email_verified=True, provider="google"
        )


@pytest.mark.asyncio
async def test_sem_restricao_nada_muda(monkeypatch):
    """O estado de quase toda a gente. Tem de continuar a funcionar."""
    _tenant(monkeypatch)
    for value in (None, "", "   "):
        svc = _service(value, existing_user=MagicMock())
        await svc.authorise_sso_identity(
            email="quem.quer.que.seja@qualquer.com",
            email_verified=True,
            provider="google",
        )


@pytest.mark.asyncio
async def test_sem_cliente_resolvido_nao_se_impoe_dominio(monkeypatch):
    """Sem cliente não há domínio DE cliente a impor — e inventar um aqui
    trancava as instalações de um só cliente sem resolvedor."""
    monkeypatch.setattr("src.core.tenant_context.current_tenant", lambda: None)
    svc = _service("skyfirstlabs.com", existing_user=MagicMock())
    await svc.authorise_sso_identity(
        email="alguem@outra.com", email_verified=True, provider="google"
    )
