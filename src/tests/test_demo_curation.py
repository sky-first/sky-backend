"""Regras editoriais da curadoria da demo — BE-12.

Estes testes existem porque a regra que protegem é a razão de ser de
todo o trabalho: a demo antiga gerava ao vivo e respondia coisas como
"resumo de alto nível — contagem de linhas e tabelas mais usadas". Um
comando de curadoria que aceitasse esse conteúdo repetia o erro, só que
mais depressa e com ar de processo.

Metade destes testes aponta ao ficheiro curado real, não a fixtures. Um
teste que só valida exemplos inventados deixa passar o ficheiro que vai
mesmo para produção.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "scripts" / "demo" / "curated_content.json"


def _load_module():
    """Importa o script pelo caminho — `scripts/` não é um pacote."""
    spec = importlib.util.spec_from_file_location(
        "curate_demo_content", ROOT / "scripts" / "curate_demo_content.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


curate = _load_module()


def _minimal_spec(**over):
    spec = {
        "vertical": "saas",
        "locale": "en",
        "name": "X",
        "insight": {
            "severity": "revenue_at_risk",
            "agent_name": "A",
            "title": "Enterprise accounts paying for seats they stopped using",
            "summary": "Seat utilisation moves months before the cancellation.",
            "stat_tiles": [{"label": "a", "value": "1"}],
            "sources": [],
            "executed_sql": "SELECT 1",
        },
        "qas": [
            {
                "question": f"Q{i}",
                "answer_markdown": "A",
                "is_suggested": i < 3,
                # As sugeridas tem de trazer numeros: descrever a
                # analise nao e responder.
                **({"stat_tiles": [{"label": "x", "value": "1"}]} if i < 3 else {}),
            }
            for i in range(5)
        ],
    }
    spec.update(over)
    return spec


# ── a regra editorial ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_question",
    [
        "Give me a high-level summary of the data",
        "What is the row count per table?",
        "Which is the most used table?",
        "Qual é a contagem de linhas?",
    ],
)
def test_conteudo_sobre_metadados_e_recusado(bad_question):
    """Foi este género de resposta que arruinou a demo antiga."""
    spec = _minimal_spec()
    spec["qas"][0]["question"] = bad_question

    problems = curate._editorial_problems(spec)

    assert any("metadados" in p for p in problems)


def test_insight_sem_sql_e_recusado():
    """Sem 'ver o SQL' o ecrã perde o elemento de prova mais barato que
    tem — passa a ser um gerador de texto com ar convincente."""
    spec = _minimal_spec()
    spec["insight"]["executed_sql"] = None

    assert any("executed_sql" in p for p in curate._editorial_problems(spec))


def test_menos_de_tres_sugeridas_e_recusado():
    spec = _minimal_spec()
    for qa in spec["qas"]:
        qa["is_suggested"] = False
    spec["qas"][0]["is_suggested"] = True

    assert any("sugeridas" in p for p in curate._editorial_problems(spec))


def test_sem_perguntas_de_reserva_e_recusado():
    """Se todas forem sugeridas, o fallback de /demo/ask fica sem alvos
    distintos das três que o visitante já tem no ecrã."""
    spec = _minimal_spec()
    for qa in spec["qas"]:
        qa["is_suggested"] = True

    assert any("fallback" in p for p in curate._editorial_problems(spec))


def test_vertical_invalida_e_recusada():
    """O CHECK da base recusaria na mesma, mas com um erro de driver a
    meio da transacção em vez de uma mensagem legível."""
    assert any(
        "vertical" in p for p in curate._editorial_problems(_minimal_spec(vertical="fintech"))
    )


def test_spec_valida_passa():
    assert curate._editorial_problems(_minimal_spec()) == []


# ── o ficheiro que vai mesmo para produção ──────────────────────────


def _real_datasets():
    return json.loads(CONTENT.read_text(encoding="utf-8"))["datasets"]


def test_ficheiro_curado_passa_as_proprias_regras():
    for spec in _real_datasets():
        assert curate._editorial_problems(spec) == [], spec["vertical"]


def test_um_default_por_idioma():
    """Um por idioma, não um no total.

    O índice parcial na base é `unique (locale) where is_default`, e é
    isso que tem de ser espelhado aqui: dois defaults no mesmo idioma
    tornariam a entrada da demo não-determinista, mas o inglês e o
    português precisam cada um do seu."""
    from collections import Counter

    counts = Counter(d.get("locale", "en") for d in _real_datasets() if d.get("is_default"))

    assert counts, "sem default nenhum, quem carrega em Saltar vai parar a lado nenhum"
    assert all(n == 1 for n in counts.values()), dict(counts)


def test_todo_o_numero_mostrado_tem_sql_por_tras():
    """A regra que separa esta demo de uma mockup: nenhum stat_tile pode
    trazer um valor escrito à mão, porque um valor escrito à mão
    envelhece em silêncio e o prospect consegue conferi-lo."""
    for spec in _real_datasets():
        for tile in spec["insight"]["stat_tiles"]:
            assert "value_sql" in tile, tile["label"]


def test_perguntas_curadas_tem_sql_e_citacoes():
    for spec in _real_datasets():
        for qa in spec["qas"]:
            assert qa.get("executed_sql"), qa["question"]
            assert qa.get("citations"), qa["question"]


def test_perguntas_sugeridas_trazem_numeros():
    """A queixa que motivou isto: "contas marcadas como risco, ordenadas
    pela receita mensal" descreve a query e não responde a nada. Uma
    demo que fala sobre números sem os mostrar perde o argumento que
    estava a tentar fazer."""
    for spec in _real_datasets():
        for qa in spec["qas"]:
            if not qa.get("is_suggested"):
                continue
            tiles = qa.get("stat_tiles") or []
            assert tiles, f"{spec['locale']}: {qa['question'][:50]!r}"
            for tile in tiles:
                assert "value_sql" in tile, tile["label"]


def test_sql_do_ficheiro_curado_e_sintacticamente_valido():
    """Não corre contra a base — só garante que é SQL e não texto. A
    execução real é o `--verify-sql`, que precisa das credenciais da
    base sintética."""
    import sqlparse  # noqa: F401  (só para falhar cedo se faltar)

    for spec in _real_datasets():
        for _label, sql in curate._all_sql(spec):
            parsed = sqlparse.parse(sql)
            assert parsed, sql[:60]
            assert parsed[0].get_type() == "SELECT", sql[:60]
