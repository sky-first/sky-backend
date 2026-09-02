"""Os scripts de demonstracao tem de escrever na base do cliente.

Escritos antes do modelo multi-cliente, olhavam sempre para o
`DATABASE_URL` — a base da plataforma. As 5 ligacoes e os 4 espacos de
demonstracao mudaram-se para a base do cliente `sandbox`, e sobrou na
plataforma um espaco `Demo` vazio.

Nenhum dos dois dava erro. O seed encontrava o espaco antigo e dizia
`refreshed` cinco vezes; o teste perguntava no sitio certo e nao
encontrava nada. Vinte perguntas a falhar a 0 ms, e o Job a passar.

Sao dois ficheiros, e a regra e a mesma nos dois — por isso o teste
tambem e o mesmo, corrido sobre ambos.
"""

import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ["smoke_test_e2e.py", "seed_demo_knowledge.py"]


@pytest.mark.parametrize("nome", SCRIPTS)
def test_a_sessao_passa_pelo_resolvedor(nome):
    """Nenhum `async with` pode abrir o AsyncSessionLocal a direito.

    Procura-se pela ARVORE e nao pelo texto: a primeira versao deste
    teste exigia a linha exacta, e o `black` reescreveu-a a tirar uns
    parenteses. Um teste que se parte com formatacao nao esta a proteger
    comportamento nenhum.
    """
    fonte = (RAIZ / "scripts" / nome).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    directos = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.AsyncWith, ast.With)):
            continue
        for item in no.items:
            alvo = item.context_expr
            if isinstance(alvo, ast.Await):
                alvo = alvo.value
            if (
                isinstance(alvo, ast.Call)
                and isinstance(alvo.func, ast.Name)
                and alvo.func.id == "AsyncSessionLocal"
            ):
                directos.append(no.lineno)

    assert not directos, (
        f"{nome}:{directos} abre a sessao directamente sobre o DATABASE_URL — "
        "escreve na base da plataforma, nao na do cliente"
    )


@pytest.mark.parametrize("nome", SCRIPTS)
def test_o_resolvedor_honra_o_tenant_slug(nome):
    fonte = (RAIZ / "scripts" / nome).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    sessao = next(
        (
            n
            for n in ast.walk(arvore)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_sessao"
        ),
        None,
    )
    assert sessao is not None, f"{nome} nao tem _sessao()"
    corpo = ast.get_source_segment(fonte, sessao)
    assert "TENANT_SLUG" in corpo, f"{nome}: _sessao() ignora o TENANT_SLUG"
    assert (
        "url_do_tenant" in corpo
    ), f"{nome}: _sessao() nao resolve a base dedicada a partir do registo"


@pytest.mark.parametrize("nome", SCRIPTS)
def test_sem_slug_nada_muda(nome):
    """Quem nao pede um cliente continua a usar o DATABASE_URL."""
    fonte = (RAIZ / "scripts" / nome).read_text(encoding="utf-8")
    assert (
        "if not slug:\n        return AsyncSessionLocal()" in fonte
    ), f"{nome}: sem TENANT_SLUG tem de continuar a usar o DATABASE_URL"
