"""O arranque do SSO tem de poder receber o cliente em parâmetro.

Porque existe este caso, e porque não é preguiça de quem escreveu a app:

O passo 1 do SSO (``/auth/sso/{provider}/login``) é aberto no **browser do
sistema** — é requisito da Google desde 2017 que a autenticação não corra
dentro de uma WebView da aplicação. Uma navegação do browser não leva
cabeçalhos nossos, portanto o ``X-Tenant-Slug`` que a app usa em todo o
lado não chega ali.

Sem o parâmetro, ``_slug_from_request`` devolvia ``None`` nesse passo, o
``state`` ficava preso à plataforma, e quem entrasse por SSO era procurado
na base da plataforma em vez da do seu cliente.

O que torna esta avaria desagradável é que **o login funciona**. O Lucas
tem conta nos dois sítios: entrava, via um espaço vazio, e não havia nada
no ecrã a dizer que estava no sítio errado.

O parâmetro não é uma porta: não dá acesso a nada por si só. O ``state``
devolvido fica assinado e presa a este cliente, o retorno é verificado
contra ele, e o ``sso_domain_restriction`` continua a exigir que o email
pertença ao domínio que o cliente declarou.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.api.v1.auth import _slug_from_request


def _pedido(*, host: str = "api.skyfirstlabs.com", cabecalhos=None, query=None):
    return SimpleNamespace(
        headers={"host": host, **(cabecalhos or {})},
        query_params=query or {},
    )


def test_o_parametro_tenant_identifica_o_cliente():
    """O caso do telemóvel: sem sub-domínio e sem cabeçalho possível."""
    assert _slug_from_request(_pedido(query={"tenant": "skyfirstlabs"})) == "skyfirstlabs"


def test_o_parametro_e_normalizado():
    pedido = _pedido(query={"tenant": "  SkyFirstLabs  "})
    assert _slug_from_request(pedido) == "skyfirstlabs"


def test_o_cabecalho_ganha_ao_parametro():
    """Onde os dois existem, o cabeçalho é o caminho normal.

    O parâmetro é o recurso para o passo que não consegue enviar
    cabeçalhos; não deve passar à frente de quem consegue.
    """
    pedido = _pedido(
        cabecalhos={"x-tenant-slug": "sandbox"},
        query={"tenant": "skyfirstlabs"},
    )
    assert _slug_from_request(pedido) == "sandbox"


def test_o_subdominio_ganha_a_tudo():
    """O host é o mais forte dos três: não é escolhido pelo cliente da API."""
    pedido = _pedido(
        host="workspace-gbt.skyfirstlabs.com",
        cabecalhos={"x-tenant-slug": "sandbox"},
        query={"tenant": "skyfirstlabs"},
    )
    assert _slug_from_request(pedido) == "gbt"


def test_sem_nada_continua_a_ser_a_plataforma():
    """O caminho da Console, que não pode passar a resolver um cliente."""
    assert _slug_from_request(_pedido(host="console.skyfirstlabs.com")) is None


def test_parametro_vazio_nao_conta():
    """``?tenant=`` não é o mesmo que declarar um cliente."""
    assert _slug_from_request(_pedido(query={"tenant": "   "})) is None
