"""O handler do cliente indisponível está registado na app.

Porque é que isto merece um teste próprio: a primeira tentativa pôs o `except`
no middleware do resolvedor e **nunca correu**. Em Starlette os handlers
registados na app correm DENTRO da pilha de middleware, por isso o
`@app.exception_handler(Exception)` apanhava o erro primeiro e devolvia o mesmo
500 de sempre.

A correcção parecia feita, os testes de unidade do `TenantUnavailableError`
passavam, e só se descobriu que estava inerte ao sondar a produção depois do
deploy. Este teste é o que faltava para isso não voltar a acontecer: verifica o
ponto de montagem, e não só a excepção.
"""
from __future__ import annotations

from src.config.tenant_connection_manager import TenantUnavailableError
from src.main import app


def test_o_handler_esta_registado_na_app():
    """Sem registo, o `Exception` genérico ganha e volta o 500."""
    assert TenantUnavailableError in app.exception_handlers


def test_o_handler_e_mais_especifico_que_o_generico():
    """Os dois existem — o que resolve o caso é o mais específico ganhar.

    Se um dia alguém remover o registo específico, o genérico continua lá e o
    500 volta em silêncio. Este teste falha nesse dia.
    """
    assert Exception in app.exception_handlers
    assert app.exception_handlers[TenantUnavailableError] is not app.exception_handlers[Exception]


def test_o_middleware_ja_nao_finge_apanhar():
    """O `except` do middleware era código morto a prometer o que não fazia.

    Um `except` que nunca corre é pior do que nenhum: quem o lê conclui que o
    caso está tratado e não vai procurar mais.
    """
    import inspect

    from src.api.middleware import tenant_resolver

    fonte = inspect.getsource(tenant_resolver)
    assert "TenantUnavailableError" not in fonte
