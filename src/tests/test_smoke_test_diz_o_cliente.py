"""Quem pergunta a IA tem de dizer de que cliente fala.

O backend manda sempre `X-Tenant-Slug` ao servico de IA
(`src/ai/http_client.py`). O `smoke_test_e2e.py` nao mandava nada, e a IA
ia procurar as ligacoes a base da plataforma:

    HTTP 404 {"detail":"Conexao aa0f521d-... nao encontrada"}

As ligacoes existiam. O script tinha acabado de as ler — as cinco — na
base do cliente. Sem o cabecalho, quem responde procura noutro sitio.

Este teste le a arvore em vez do texto: a versao anterior de um teste
destes exigia uma linha exacta e o `black` partiu-a.
"""

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "smoke_test_e2e.py"


def _chamadas_ao_asyncclient(arvore):
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "AsyncClient"
        ):
            yield no


def test_o_cliente_http_leva_cabecalhos():
    fonte = SCRIPT.read_text(encoding="utf-8")
    chamadas = list(_chamadas_ao_asyncclient(ast.parse(fonte)))
    assert chamadas, "nao encontrei httpx.AsyncClient(...)"
    for c in chamadas:
        nomes = {k.arg for k in c.keywords}
        assert "headers" in nomes, (
            f"linha {c.lineno}: AsyncClient sem headers — a IA nao sabe de que "
            "cliente falamos e procura na base da plataforma"
        )


def test_o_cabecalho_e_o_que_o_backend_usa():
    """`X-Tenant-Slug`, o mesmo nome. Outro qualquer e ignorado em silencio."""
    fonte = SCRIPT.read_text(encoding="utf-8")
    assert "X-Tenant-Slug" in fonte
    backend = (RAIZ / "src" / "ai" / "http_client.py").read_text(encoding="utf-8")
    assert (
        "X-Tenant-Slug" in backend
    ), "o backend mudou o nome do cabecalho — o smoke test tem de acompanhar"


def test_sem_slug_nao_se_inventa_cabecalho():
    """Sem TENANT_SLUG o comportamento antigo mantem-se."""
    fonte = SCRIPT.read_text(encoding="utf-8")
    assert 'if slug:\n        cabecalhos["X-Tenant-Slug"] = slug' in fonte
