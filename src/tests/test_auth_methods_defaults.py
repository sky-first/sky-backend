"""Defeitos dos métodos de autenticação.

Duas coisas que partilhavam o mesmo valor e não deviam:

* o que um cliente NOVO recebe — password, porque é a base que funciona
  sempre e porque a pipeline gera-lhe uma password de admin;
* o que a plataforma responde quando não há cliente resolvido — password
  **e** Google, porque é por aí que a equipa da Sky entra.

Trocar o primeiro sem separar o segundo fazia desaparecer o botão do
Google no login da equipa.
"""

from __future__ import annotations

from src.models.tenant import DEFAULT_AUTH_METHODS, PLATFORM_FALLBACK_AUTH_METHODS


def test_cliente_novo_nasce_com_password():
    """Sem isto o cliente nascia inacessível.

    A pipeline de provisionamento gera uma password de admin e guarda-a
    em `sky/production/tenant-<slug>/admin`. Se a password estiver
    desligada, essa credencial não serve para nada e alguém tem de ir
    ligar o método à mão antes de o cliente conseguir entrar.
    """
    assert DEFAULT_AUTH_METHODS["password"] is True


def test_cliente_novo_nao_nasce_com_sso_ligado():
    """Nenhum método que ninguém escolheu.

    O Google ligado por omissão era superfície aberta de graça em todo o
    cliente criado — e foi por aí que entrou a falha do SSO. Quem quiser
    SSO liga-o e declara os domínios da empresa.
    """
    assert DEFAULT_AUTH_METHODS["google"] is False
    assert DEFAULT_AUTH_METHODS["azure"] is False
    assert DEFAULT_AUTH_METHODS["okta"] is False


def test_a_plataforma_e_so_sso():
    """O login da equipa é só Google — decisão do Lucas, 15/08/2026.

    A equipa entra com contas @skyfirstlabs.com do Google Workspace e,
    como esse domínio ainda não está registado, cai no caminho de
    "nenhum cliente resolvido". Se este valor seguisse o defeito dos
    clientes novos, o botão do Google desaparecia — daí serem duas
    constantes.

    E a palavra-passe fica FORA: seria uma segunda porta para a própria
    plataforma, a superfície mais sensível que há, e ninguém a usa.
    """
    assert PLATFORM_FALLBACK_AUTH_METHODS["google"] is True
    assert PLATFORM_FALLBACK_AUTH_METHODS["password"] is False


def test_os_dois_defeitos_sao_mesmo_diferentes():
    """Guarda contra alguém voltar a fundi-los por arrumação."""
    assert DEFAULT_AUTH_METHODS != PLATFORM_FALLBACK_AUTH_METHODS


def test_pelo_menos_um_metodo_ligado_em_ambos():
    """Um conjunto todo a falso tranca toda a gente fora."""
    for nome, metodos in (
        ("clientes novos", DEFAULT_AUTH_METHODS),
        ("plataforma", PLATFORM_FALLBACK_AUTH_METHODS),
    ):
        assert any(metodos.values()), f"{nome}: nenhum método de entrada ligado"
