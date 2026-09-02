"""O teste diario nao pode ser a maior carga que o servico leva.

A 02/09/2026, na primeira corrida honesta, o servico de IA morreu a meio
— `OOMKilled` — e levou quatro perguntas com ele. So existe uma replica,
por isso isso e a app em baixo para toda a gente.

A carga nao vinha dos utilizadores. Vinha deste teste: passava
`skip_if_recent_seconds=0`, o que reindexa as cinco ligacoes a cada
passagem. Parado, o servico ocupa 202 MB.

Um teste que derruba o que esta a medir nao mede nada.
"""

import ast
import os
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "smoke_test_e2e.py"


def _fonte() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _linhas_de_codigo() -> list[str]:
    """So codigo: a primeira versao deste teste apanhou o seu proprio comentario.

    Um teste que se queixa da explicacao do defeito, e nao do defeito, e
    ruido — e ensina a apagar comentarios para o calar.
    """
    fonte = _fonte()
    arvore = ast.parse(fonte)
    docstrings = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(no, clean=False)
            if d:
                docstrings.update(d.split(chr(10)))
    saida = []
    for linha in fonte.split(chr(10)):
        nua = linha.strip()
        if nua.startswith("#") or nua in docstrings:
            continue
        saida.append(linha)
    return saida


def test_nao_forca_reindexacao_a_cada_passagem():
    maus = [l for l in _linhas_de_codigo() if "skip_if_recent_seconds=0" in l]
    assert not maus, (
        "o teste volta a reindexar tudo a cada corrida — foi assim que "
        f"derrubou o servico de IA a 02/09: {maus}"
    )


def test_a_idade_maxima_e_configuravel():
    """`SMOKE_DISCOVER_MAX_AGE=0` para quando se quiser testar a indexacao."""
    assert "SMOKE_DISCOVER_MAX_AGE" in _fonte()


def test_o_valor_por_omissao_cobre_a_corrida_diaria():
    """O Job tem TTL de 24h, logo corre uma vez por dia.

    Se a idade maxima fosse maior do que 24h, a indexacao nunca se
    refrescaria; se fosse curta de mais, voltavamos ao problema.
    """
    fonte = _fonte()
    m = re.search(r'SMOKE_DISCOVER_MAX_AGE",\s*"(\d+)"', fonte)
    assert m, "nao encontrei o valor por omissao"
    segundos = int(m.group(1))
    assert 3600 <= segundos < 86400, (
        f"{segundos}s: ou reindexa de mais, ou nunca mais refresca "
        "(o Job corre de 24 em 24 horas)"
    )
