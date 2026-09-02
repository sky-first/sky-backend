"""O teste de fumo tem de falhar quando as perguntas falham.

Ate 02/09/2026 imprimia `PASS=0/20` e saia com 0. Como Job de Kubernetes
isso e `Complete 1/1`: o ArgoCD ve saude, o `kubectl get jobs` ve
sucesso, e o relatorio com vinte FAIL fica dentro dos logs a espera de
que alguem os abra.

Foi assim que se descobriu, a 02/09: o Job passou, e so a ler os logs se
viu que nenhuma das vinte perguntas tinha chegado a sair.
"""

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "smoke_test_e2e.py"


def _funcao(nome: str) -> ast.AsyncFunctionDef:
    arvore = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, (ast.AsyncFunctionDef, ast.FunctionDef)) and no.name == nome:
            return no
    raise AssertionError(f"nao encontrei a funcao {nome!r}")


def test_main_devolve_codigo_de_saida():
    """Sem `return`, o `sys.exit` do fundo recebe None — que e sair com 0."""
    retornos = [
        n for n in ast.walk(_funcao("main")) if isinstance(n, ast.Return) and n.value is not None
    ]
    assert retornos, (
        "o main() nao devolve nada: o Job termina sempre em sucesso, "
        "mesmo com as vinte perguntas a falhar"
    )


def test_o_codigo_de_saida_depende_do_resultado():
    """Um `return 0` fixo passaria no teste acima e nao daria sinal nenhum."""
    fonte = ast.get_source_segment(SCRIPT.read_text(encoding="utf-8"), _funcao("main"))
    assert (
        "return 0 if ok == len(results) else 1" in fonte
    ), "o codigo de saida tem de depender de quantas perguntas passaram"


def test_a_saida_do_processo_usa_esse_codigo():
    """`asyncio.run(main())` sem `sys.exit` deita o codigo fora."""
    fonte = SCRIPT.read_text(encoding="utf-8")
    assert (
        "sys.exit(asyncio.run(main()))" in fonte
    ), "o valor devolvido pelo main() nao chega ao codigo de saida do processo"
