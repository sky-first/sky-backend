"""A Google recusa `sky://` — o SSO no telemóvel nunca chegou a funcionar.

O que acontecia
---------------
A app mandava ``redirect_uri=sky://auth``; o backend passava-o tal e qual
ao fornecedor; a Google respondia:

    Erro 400: invalid_request
    You can't sign in to this app because it doesn't comply with Google's
    OAuth 2.0 policy for keeping apps secure

Esquemas próprios só são aceites em clientes OAuth de **Android/iOS**, e o
que existe é um cliente **Web**. Estava escrito num aviso no `sso.ts` desde
que o fluxo foi montado — e ninguém tinha ligado o aviso ao sintoma, porque
ninguém tinha entrado por SSO no telefone: o revisor do sandbox usa
password. O primeiro cliente só-SSO expô-lo.

A forma escolhida
-----------------
O fornecedor recebe sempre um ``https`` nosso; o endereço da app viaja
**assinado** dentro do ``state``, que já existia e já era verificado.

O que NÃO se faz — e é o ponto destes testes — é mandar os tokens no salto
de volta. Num esquema próprio, qualquer app instalada que declare ``sky://``
recebe o intent. Vai um código de uso único, com 60 segundos, que morre à
primeira troca.
"""
from __future__ import annotations

import pytest

from src.core.sso_state import app_redirect_from_state, issue_state, verify_state
from src.core import sso_handoff


# ─── O que decide qual dos dois caminhos se segue ─────────────────────
@pytest.mark.parametrize(
    "uri,e_de_app",
    [
        ("sky://auth", True),
        ("exp://192.168.1.75:8081/--/auth", True),  # Expo em desenvolvimento
        ("com.skyfirstlabs.sky://oauth", True),
        ("https://app.skyfirstlabs.com/login/sso/callback", False),
        ("http://localhost:3000/login/sso/callback", False),
        ("HTTPS://APP.SKYFIRSTLABS.COM/x", False),  # esquema em maiúsculas
        ("", False),
        (None, False),
        ("sky:/sem-duas-barras", False),  # não é um endereço; não desvia nada
    ],
)
def test_reconhece_um_endereco_de_app(uri, e_de_app):
    assert sso_handoff.is_app_scheme(uri) is e_de_app


def test_o_caminho_da_web_nao_muda():
    """A regressão que mais importa evitar.

    O login na web funciona há meses. Um `redirect_uri` https não pode
    passar a ser tratado como app — isso mandava o browser saltar para um
    esquema que ele não sabe abrir.
    """
    assert sso_handoff.is_app_scheme("https://app.skyfirstlabs.com/login/sso/callback") is False


# ─── O endereço da app viaja assinado ─────────────────────────────────
def test_o_state_leva_e_devolve_o_endereco_da_app():
    state = issue_state("skyfirstlabs", "sky://auth")
    verify_state(state, "skyfirstlabs")  # continua válido para o cliente
    assert app_redirect_from_state(state) == "sky://auth"


def test_sem_endereco_de_app_o_state_e_o_de_sempre():
    state = issue_state("skyfirstlabs")
    verify_state(state, "skyfirstlabs")
    assert app_redirect_from_state(state) is None


def test_um_state_adulterado_nao_devolve_endereco():
    """O ponto todo de o endereço ir assinado.

    Sem isto, quem interceptasse o retorno trocava o endereço pelo de
    outra app e recebia a sessão no lugar de quem estava a entrar.
    """
    state = issue_state("skyfirstlabs", "sky://auth")
    corpo, _, assinatura = state.partition(".")
    forjado = f"{corpo}.{'0' * len(assinatura)}"
    assert app_redirect_from_state(forjado) is None


def test_o_endereco_nao_afrouxa_a_verificacao_do_cliente():
    """Um state de outro workspace continua a ser recusado."""
    from src.core.sso_state import SSOStateError

    state = issue_state("gbtsolutions", "sky://auth")
    with pytest.raises(SSOStateError):
        verify_state(state, "skyfirstlabs")


# ─── O código de entrega ──────────────────────────────────────────────
class _RedisFalso:
    """O mínimo que o módulo usa: `set` com expiração e `getdel`."""

    def __init__(self):
        self.dados = {}

    async def set(self, chave, valor, ex=None):
        self.dados[chave] = valor

    async def getdel(self, chave):
        return self.dados.pop(chave, None)


@pytest.fixture
def redis_falso(monkeypatch):
    r = _RedisFalso()
    monkeypatch.setattr(sso_handoff, "_client", lambda: r)
    return r


@pytest.mark.asyncio
async def test_o_codigo_devolve_o_que_foi_guardado(redis_falso):
    code = await sso_handoff.issue({"login": {"access_token": "a"}, "tenant": "skyfirstlabs"})
    assert await sso_handoff.consume(code) == {
        "login": {"access_token": "a"},
        "tenant": "skyfirstlabs",
    }


@pytest.mark.asyncio
async def test_o_codigo_so_serve_uma_vez(redis_falso):
    """É isto que limita o estrago de uma intercepção do intent.

    Se pudesse ser usado duas vezes, interceptar o salto dava a sessão a
    quem interceptou E ao utilizador — e ninguém dava por nada.
    """
    code = await sso_handoff.issue({"login": {"access_token": "a"}})
    await sso_handoff.consume(code)
    with pytest.raises(sso_handoff.HandoffError):
        await sso_handoff.consume(code)


@pytest.mark.asyncio
async def test_codigo_inexistente_e_recusado(redis_falso):
    with pytest.raises(sso_handoff.HandoffError):
        await sso_handoff.consume("nao-existe")


@pytest.mark.asyncio
async def test_codigo_vazio_e_recusado(redis_falso):
    with pytest.raises(sso_handoff.HandoffError):
        await sso_handoff.consume("")


@pytest.mark.asyncio
async def test_dois_codigos_nunca_coincidem(redis_falso):
    a = await sso_handoff.issue({"login": {}})
    b = await sso_handoff.issue({"login": {}})
    assert a != b
    assert len(a) > 30  # entropia suficiente para 60s de vida


@pytest.mark.asyncio
async def test_redis_em_baixo_recusa_em_vez_de_deixar_passar(monkeypatch):
    """Falhar fechado.

    Sem o Redis não há como saber se um código já foi usado. Recusar um
    login é preferível a aceitar um código que outra pessoa já pode ter
    gasto.
    """

    class _Partido:
        async def getdel(self, chave):
            raise RuntimeError("redis em baixo")

        async def set(self, *a, **k):
            raise RuntimeError("redis em baixo")

    monkeypatch.setattr(sso_handoff, "_client", lambda: _Partido())
    with pytest.raises(sso_handoff.HandoffError):
        await sso_handoff.consume("seja-o-que-for")
    with pytest.raises(sso_handoff.HandoffError):
        await sso_handoff.issue({"login": {}})


def test_a_vida_do_codigo_e_curta():
    """60s chega para o salto do browser para a app e não mais.

    Se alguém alargar isto para minutos, a janela de intercepção cresce na
    mesma proporção — e este teste obriga a pensar nisso.
    """
    assert sso_handoff.HANDOFF_TTL_SECONDS <= 120
