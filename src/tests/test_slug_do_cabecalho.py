"""O `X-Tenant-Slug` que conta é o primeiro — e vem sem espaços nem maiúsculas.

Um cabeçalho HTTP repetido chega juntado por vírgulas; é o que a norma manda.
O resolvedor passava o valor tal e qual para a procura no registo, e
`"sandbox, outro"` não é cliente nenhum: o pedido levaria `tenant_not_found`
com um cliente que existe e está bom — uma falha que culpa o cliente, que
está bom.

**Isto é uma defesa, não a correcção de uma avaria observada.** Nenhum dos
saltos de hoje repete o cabeçalho. O que se via mesmo era o mais banal:
espaços à volta e maiúsculas, que os slugs na base não têm.
"""

import pytest

from src.api.middleware.tenant_resolver import slug_do_cabecalho


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        # **O caso que partiu.** Fica-se pelo primeiro: é o que a origem
        # escreveu, e o que um intermediário acrescenta a seguir não pode
        # mandar mais do que ela.
        ("local, localhost", "local"),
        ("sandbox,proxy-interno,outro", "sandbox"),
        # Sem vírgulas, nada muda — é o caminho de todos os dias.
        ("sandbox", "sandbox"),
        # Espaços e maiúsculas: os slugs são minúsculos na base, e um
        # `X-Tenant-Slug: Sandbox` de um cliente novo não pode dar 404.
        (" SANDBOX ", "sandbox"),
        ("local ,localhost", "local"),
        # Vazio é ausência, e não um cliente chamado "".
        ("", None),
        (None, None),
        ("   ", None),
        # Só vírgulas não deixam nada de útil — e um slug vazio prendia o
        # pedido a "" em vez de a ninguém.
        (",", None),
        (" , sandbox", None),
    ],
)
def test_o_slug_que_conta_e_o_primeiro(bruto, esperado):
    assert slug_do_cabecalho(bruto) == esperado


def test_o_resolvedor_usa_isto_e_nao_o_cabecalho_em_cru():
    """Senão a correcção vive numa função que ninguém chama."""
    import inspect

    from src.api.middleware import tenant_resolver

    fonte = inspect.getsource(tenant_resolver._resolve_context)
    assert 'slug_do_cabecalho(request.headers.get("x-tenant-slug"))' in fonte
    # E não sobra nenhuma leitura crua a seguir a esta.
    assert 'or request.headers.get("x-tenant-slug")' not in fonte


def test_o_auth_methods_segue_o_mesmo_caminho():
    """Dois sítios a ler o mesmo cabeçalho de maneiras diferentes divergem.

    E a divergência aparecia como o login a dizer que o cliente não permite
    palavra-passe, num cliente que permite.
    """
    import inspect

    from src.api.v1 import auth

    fonte = inspect.getsource(auth._slug_from_request)
    assert "slug_do_cabecalho" in fonte
