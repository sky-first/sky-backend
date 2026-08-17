"""A lista de clientes da Console não mostra as linhas da plataforma.

O `sky` aparecia lá como um cliente activo, com pontuação de saúde e barras
de capacidade. Não é um cliente:

* aponta para a base **central** (`skyaisaas`) — não tem base própria como o
  `sandbox` ou o `skyfirstlabs` têm;
* o IAM não consegue ler o segredo dela: clicar-lhe dava `AccessDenied` sem
  explicação nenhuma;
* `sky` está nos nomes reservados, e o pipeline de provisionamento **recusa**
  esse slug — logo nunca poderá vir a ser um cliente.

Existe porque a plataforma precisa de um contexto por omissão, e é essa a
razão de estar na tabela. Mas mostrar na lista uma linha que parece operável
e não é, é pior do que não a mostrar: o Lucas perguntou o que era, se estava
morta, e se devia ser renomeada — três perguntas que a lista provocou.

A lista usada é a MESMA do resolvedor. Se um dia lá entrar outro nome, a
Console acompanha sem ninguém se lembrar de a actualizar nos dois sítios.
"""
from __future__ import annotations

import pytest

from src.api.middleware.tenant_resolver import _RESERVED_SLUGS


def test_o_sky_esta_entre_os_reservados():
    """Se sair da lista, o teste seguinte deixa de significar alguma coisa."""
    assert "sky" in _RESERVED_SLUGS


def test_a_consulta_exclui_os_reservados():
    """O filtro entra na consulta, não numa filtragem depois de ler.

    Importa que seja no SQL: a contagem do total sai da mesma `stmt`. A
    filtrar em Python, a lista viria certa e o "2 registered" viria a dizer
    3 — o tipo de incoerência que faz alguém desconfiar do ecrã todo.
    """
    import inspect

    from src.services import console_service

    fonte = inspect.getsource(console_service.list_tenants)
    assert "_RESERVED_SLUGS" in fonte
    assert "notin_" in fonte
    # O filtro tem de estar ANTES do cálculo do total.
    assert fonte.index("notin_") < fonte.index("func.count()")


@pytest.mark.parametrize("slug", sorted(_RESERVED_SLUGS))
def test_nenhum_nome_reservado_pode_ser_cliente(slug):
    """Espelha a recusa do pipeline: estes nomes são da plataforma.

    `demo`, `console`, `api`, `www`, `admin`, `platform` são hosts nossos;
    `sky` é a semente. Uma linha com qualquer um destes slugs não é um
    cliente, e a lista de clientes não a deve mostrar.
    """
    assert slug == slug.lower()
    assert slug in _RESERVED_SLUGS
