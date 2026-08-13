"""Isolamento entre clientes no fluxo de SSO.

Cobre a matriz de testes de docs/SEGURANCA-SSO-E-ISOLAMENTO-TENANT.md.

Contexto: o retorno do SSO criava utilizadores dentro do cliente em que a
ligação calhasse cair, sem verificar se o email pertencia àquele cliente,
e o ``state`` do OAuth era recebido e ignorado. Estes testes fixam o
comportamento corrigido para que não volte atrás.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import ForbiddenError
from src.core.sso_state import (
    SSOStateError,
    issue_state,
    verify_state,
)
from src.services.auth0_service import Auth0Service


# ── state assinado (T4 a T7) ────────────────────────────────────────


def test_state_valido_do_mesmo_cliente_passa():
    verify_state(issue_state("sandbox"), "sandbox")


def test_state_de_outro_cliente_e_recusado():
    """T4 — o state emitido em `outro` não serve para entrar em `sandbox`.

    É este o teste que fecha a falha: sem ele, um state obtido em
    qualquer lado servia para qualquer cliente.
    """
    with pytest.raises(SSOStateError):
        verify_state(issue_state("outro"), "sandbox")


def test_state_de_cliente_nao_serve_na_plataforma():
    with pytest.raises(SSOStateError):
        verify_state(issue_state("sandbox"), None)


def test_state_da_plataforma_nao_serve_num_cliente():
    with pytest.raises(SSOStateError):
        verify_state(issue_state(None), "sandbox")


def test_state_adulterado_e_recusado():
    """T5 — mexer no conteúdo invalida a assinatura."""
    payload, signature = issue_state("sandbox").split(".", 1)
    forjado = f"{payload}x.{signature}"
    with pytest.raises(SSOStateError):
        verify_state(forjado, "sandbox")


def test_assinatura_trocada_e_recusada():
    payload, _ = issue_state("sandbox").split(".", 1)
    _, outra_assinatura = issue_state("outro").split(".", 1)
    with pytest.raises(SSOStateError):
        verify_state(f"{payload}.{outra_assinatura}", "sandbox")


def test_state_expirado_e_recusado():
    """T6 — passado o TTL, não vale."""
    with patch("src.core.sso_state.time.time", return_value=time.time() - 3600):
        velho = issue_state("sandbox")
    with pytest.raises(SSOStateError):
        verify_state(velho, "sandbox")


@pytest.mark.parametrize("valor", [None, "", "sem-ponto", "a.b.c", "..", "x."])
def test_state_ausente_ou_malformado_e_recusado(valor):
    """T7 — nada disto pode passar por engano."""
    with pytest.raises(SSOStateError):
        verify_state(valor, "sandbox")


# ── porta de entrada do SSO (T1, T3, T8, T9) ────────────────────────


def _servico(*, utilizador_existente, jit_ligado: bool) -> Auth0Service:
    """Auth0Service com o repositório e o contexto de cliente simulados."""
    servico = Auth0Service.__new__(Auth0Service)
    servico.user_repo = MagicMock()
    servico.user_repo.get_by_email = AsyncMock(return_value=utilizador_existente)
    servico.db = MagicMock()
    servico._jit_provisioning_enabled = staticmethod(lambda: jit_ligado)
    return servico


async def test_conta_desconhecida_sem_jit_e_recusada():
    """T1 — o caso que estava aberto: uma conta Google qualquer.

    Antes, isto criava o utilizador dentro do cliente e dava-lhe um
    espaço de trabalho.
    """
    servico = _servico(utilizador_existente=None, jit_ligado=False)
    with pytest.raises(ForbiddenError):
        await servico.authorise_sso_identity(
            email="estranho@gmail.com", email_verified=True, provider="google"
        )


async def test_conta_desconhecida_com_jit_ligado_passa():
    """T3 — provisionamento automático é uma escolha explícita do cliente."""
    servico = _servico(utilizador_existente=None, jit_ligado=True)
    await servico.authorise_sso_identity(
        email="novo@cliente.com", email_verified=True, provider="google"
    )


@pytest.mark.parametrize("verificado", [False, None])
async def test_email_nao_verificado_nao_se_cola_a_conta_existente(verificado):
    """T8 — tomada de conta: identidade não verificada sobre conta com password."""
    servico = _servico(
        utilizador_existente=SimpleNamespace(email="lucas@ikea.com"), jit_ligado=False
    )
    with pytest.raises(ForbiddenError):
        await servico.authorise_sso_identity(
            email="lucas@ikea.com", email_verified=verificado, provider="google"
        )


async def test_email_verificado_liga_se_a_conta_existente():
    """T9 — o caso legítimo continua a funcionar."""
    servico = _servico(
        utilizador_existente=SimpleNamespace(email="lucas@ikea.com"), jit_ligado=False
    )
    await servico.authorise_sso_identity(
        email="lucas@ikea.com", email_verified=True, provider="google"
    )


async def test_jit_desligado_quando_nao_ha_cliente_resolvido():
    """Na dúvida, não criar.

    Sem cliente em contexto, o provisionamento automático tem de contar
    como desligado — senão um pedido que não resolve cliente ganhava
    mais permissões do que um que resolve.
    """
    with patch("src.core.tenant_context.current_tenant", return_value=None):
        assert Auth0Service._jit_provisioning_enabled() is False
