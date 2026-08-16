"""Um cliente não pode chamar-se como um host nosso.

Esta regra não existia — e não precisava de existir. Até 16/08/2026 um host
simples (`app.skyfirstlabs.com`) nunca resolvia cliente nenhum, por isso um
cliente chamado `app` era inofensivo: ficava lá na lista sem efeito.

O #619 mudou isso. Desde que o resolvedor aceita `<slug>.skyfirstlabs.com`,
criar um cliente com o slug `app` faz o endereço principal do produto passar
a servir esse cliente. O mesmo para `console` (a Console dos operadores),
`api` (o host da app móvel) e `demo`.

Ou seja: a mesma alteração que deu endereço próprio a cada cliente
transformou a lista de reservados, que era um detalhe do resolvedor, numa
regra de criação. Este ficheiro é a regra.

Onde ela NÃO estava
-------------------
- A Console não validava slugs contra nada.
- O comentário no `tenant_resolver` afirmava que "o workflow onboard-client
  recusa estes slugs ao criar". **Não recusa**: a lista dele são nomes de
  namespaces do Kubernetes (`argocd`, `kube-system`, `default`, `staging`,
  `production`, `sky-system`, `monitoring`) e não inclui um único destes.
  O comentário foi escrito, lido, e repetido por mim numa conversa antes de
  alguém o ir verificar.

Não é explorável de fora — só um operador cria clientes. É um pé-de-galinha
interno, do tipo que derruba o endereço principal numa terça-feira à tarde.
"""
from __future__ import annotations

import pytest

from src.api.middleware.tenant_resolver import _RESERVED_SLUGS


@pytest.mark.parametrize(
    "slug,host_que_seria_sequestrado",
    [
        ("app", "app.skyfirstlabs.com — o endereço do produto"),
        ("console", "console.skyfirstlabs.com — a Console dos operadores"),
        ("api", "api.skyfirstlabs.com — o host da app móvel"),
        ("demo", "demo.skyfirstlabs.com — a demo pública"),
        ("sky", "a linha-semente, que aponta para a base da plataforma"),
        ("auth", "auth-prd.skyfirstlabs.com — o oauth2-proxy"),
    ],
)
def test_hosts_nossos_estao_reservados(slug, host_que_seria_sequestrado):
    assert slug in _RESERVED_SLUGS, (
        f"'{slug}' fora da lista — um cliente com este nome ficava com "
        f"{host_que_seria_sequestrado}"
    )


def test_o_servico_recusa_um_slug_reservado():
    """A regra tem de estar no serviço, não só na lista.

    Uma lista que ninguém consulta é uma lista decorativa — foi exactamente
    o que aconteceu ao `sso_domain_restriction` e ao `custom_domain`.
    """
    import inspect

    from src.services import console_service

    fonte = inspect.getsource(console_service.create_tenant)
    assert "_RESERVED_SLUGS" in fonte
    assert "slug_reserved" in fonte
    # Antes de escrever seja o que for: um slug recusado não deve deixar
    # linha nenhuma para trás.
    assert fonte.index("_RESERVED_SLUGS") < fonte.index("Tenant(")


def test_a_rota_devolve_409_e_nao_500():
    """Sem mapeamento, o `ValueError` subia e virava 500.

    Quem está a criar um cliente merece saber que o nome está ocupado, não
    um erro genérico do servidor.
    """
    import inspect

    from src.api.v1 import console

    fonte = inspect.getsource(console.create_tenant)
    assert "slug_reserved" in fonte
    assert "409" in fonte


def test_a_comparacao_ignora_espacos_e_maiusculas():
    """`  APP  ` é o mesmo nome. Uma regra que se contorna com um espaço
    não é uma regra."""
    import inspect

    from src.services import console_service

    fonte = inspect.getsource(console_service.create_tenant)
    assert ".strip().lower()" in fonte


def test_um_nome_normal_continua_a_passar():
    """A guarda não pode apanhar clientes a sério."""
    for slug in ("gbtsolutions", "teamblue", "appsconcept", "skyfirstlabs", "sandbox"):
        assert slug not in _RESERVED_SLUGS
