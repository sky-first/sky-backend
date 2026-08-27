"""Nenhum ficheiro pode usar um nome que nunca definiu.

Apanhado em produção: um member a pedir um projeto onde não está recebia 500,
e o registo dizia

    Rate limiting error (continuing without rate limit):
    name 'select' is not defined

`select` era usado em cinco sítios do `space_service.py` e nunca importado ao
nível do módulo. Os cinco são o mesmo bloco: o que dá acesso a quem pertence a
uma **equipa** dentro do projeto sem ser membro directo dele. Ou seja, o
caminho existia, estava escrito, e rebentava sempre — trancando fora gente com
direito a entrar, com um 500 em vez de uma resposta.

Ninguém deu por isso porque o caminho só corre para quem **não** é membro
directo, e ninguém tinha testado com uma conta assim. O `ai_worker.py` tinha
exactamente o mesmo problema, e no `space_service` alguém já tropeçara e
contornara com um `from sqlalchemy import select as _select` local em vez de
corrigir o topo do ficheiro.

Este teste percorre a árvore sintáctica de todo o `src/` e compara nomes
carregados com nomes definidos. É deliberadamente conservador: só acusa o que
não está definido em lado nenhum do módulo, para não gerar ruído.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

#: Nomes que a análise estática não vê mas existem em tempo de execução.
#: Cada entrada tem de trazer a razão.
TOLERADOS = {
    # Definido pelo interpretador em qualquer módulo carregado de ficheiro.
    "__file__",
    "__name__",
    "__doc__",
}


def _nomes_por_definir(caminho: Path) -> list[str]:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    definidos = set(dir(builtins)) | TOLERADOS
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            for alias in no.names:
                definidos.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definidos.add(no.name)
        elif isinstance(no, ast.Name) and isinstance(no.ctx, ast.Store):
            definidos.add(no.id)
        elif isinstance(no, ast.arg):
            definidos.add(no.arg)
        elif isinstance(no, ast.ExceptHandler) and no.name:
            definidos.add(no.name)
        elif isinstance(no, ast.Global):
            definidos.update(no.names)

    usados = {
        n.id
        for n in ast.walk(arvore)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    return sorted(usados - definidos)


def test_nenhum_ficheiro_usa_um_nome_que_nao_definiu():
    problemas: dict[str, list[str]] = {}
    for f in RAIZ.rglob("*.py"):
        if "tests" in f.parts:
            continue
        faltam = _nomes_por_definir(f)
        if faltam:
            problemas[str(f.relative_to(RAIZ))] = faltam

    assert problemas == {}, (
        "estes nomes rebentam com NameError assim que a linha correr — e são "
        f"invisíveis até alguém percorrer esse caminho exacto: {problemas}"
    )


def test_o_select_do_space_service_esta_mesmo_importado():
    """O caso concreto, nomeado, para não se perder no teste geral acima.

    **Afirma-se que o nome existe, não a linha que o traz.** A versão
    anterior exigia a linha literal ``from sqlalchemy import select`` e
    partiu-se a 26/08, quando o ficheiro passou a precisar também de ``or_``
    e a importação virou ``from sqlalchemy import func, or_, select`` — que é
    igualmente correcta. Um teste que fixa a forma da linha em vez do que ela
    garante obriga a mexer no teste sempre que o ficheiro cresce, e não
    apanha nada que o ``NameError`` não apanhasse.
    """
    import src.services.space_service as mod

    assert hasattr(mod, "select"), "o `select` não está no âmbito do módulo"


def test_a_deteccao_funciona():
    """Sem esta guarda, um bug na análise fazia o teste acima passar sempre."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def f():\n    return coisa_que_nao_existe\n")
        caminho = Path(f.name)
    try:
        assert _nomes_por_definir(caminho) == ["coisa_que_nao_existe"]
    finally:
        caminho.unlink()
