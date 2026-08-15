"""Um cliente registado cuja base não abre não pode dar 500.

Encontrado em produção a 15/08/2026: o cliente semente `sky` aponta para a base
da plataforma e o seu segredo **não é legível** pelo papel do `sky-be`
(`AccessDeniedException` no `GetSecretValue`) — de propósito, porque ninguém
devia resolvê-lo. Só que bastava mandar `X-Tenant-Slug: sky`, **sem
autenticação nenhuma**, para a API responder:

    {"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred."}}

Um 500 que não diz nada a quem o apanha. Perdemos meia hora a adivinhar o que
era, e o `Test connection` do Console — que dá a mensagem verdadeira — só se
alcança autenticado.

A resposta passa a ser a MESMA de "cliente não existe", de propósito: o resto
do código já trata domínio desconhecido, domínio desactivado e cliente suspenso
como indistinguíveis para quem sonda de fora. Um cliente avariado não tem de
ser a excepção que confirma que ele existe.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.tenant_connection_manager import (
    TenantConnectionManager,
    TenantUnavailableError,
)


def _ctx(slug="sky"):
    ctx = MagicMock()
    ctx.slug = slug
    ctx.tier = "strategic"
    ctx.db_name = "skyaisaas"
    ctx.db_host = "sky-postgres-production.example.eu-west-1.rds.amazonaws.com"
    ctx.db_credentials_secret_arn = "arn:aws:secretsmanager:eu-west-1:1:secret:s-2Pmb7w"
    ctx.is_default = False
    return ctx


def test_segredo_ilegivel_da_erro_nomeado_e_nao_explode():
    """O caso real: `GetSecretValue` recusado pelo IAM."""
    mgr = TenantConnectionManager()
    boom = PermissionError(
        "An error occurred (AccessDeniedException) when calling the "
        "GetSecretValue operation"
    )
    with patch.object(TenantConnectionManager, "_build_url", side_effect=boom):
        with pytest.raises(TenantUnavailableError) as info:
            mgr._build_pool_sync(_ctx())
    # Leva o slug: é o que o operador precisa de ver no log.
    assert info.value.slug == "sky"


def test_a_causa_original_nao_se_perde():
    """Sem `from exc`, o traço no log ficava sem a razão verdadeira — e era
    justamente a razão que faltava quando isto apareceu."""
    mgr = TenantConnectionManager()
    causa = PermissionError("AccessDeniedException")
    with patch.object(TenantConnectionManager, "_build_url", side_effect=causa):
        with pytest.raises(TenantUnavailableError) as info:
            mgr._build_pool_sync(_ctx())
    assert info.value.__cause__ is causa


def test_qualquer_falha_de_ligacao_conta():
    """Segredo ilegível, host errado, base por criar — para quem chama são a
    mesma coisa: o cliente não serve agora."""
    mgr = TenantConnectionManager()
    for boom in (
        KeyError("secret has neither username/password nor url"),
        OSError("could not translate host name"),
        ValueError("malformed url"),
    ):
        with patch.object(TenantConnectionManager, "_build_url", side_effect=boom):
            with pytest.raises(TenantUnavailableError):
                mgr._build_pool_sync(_ctx())


def test_um_cliente_saudavel_continua_a_construir():
    """A rede de segurança não pode apanhar o caso normal."""
    mgr = TenantConnectionManager()
    with patch.object(
        TenantConnectionManager, "_build_url", return_value="sqlite+aiosqlite:///:memory:"
    ):
        pool = mgr._build_pool_sync(_ctx("gbtsolutions"))
    assert pool.engine is not None
    assert pool.session_maker is not None
