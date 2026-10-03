# -*- coding: utf-8 -*-
"""Os sectores novos da demo pública estão ligados de ponta a ponta.

Um sector novo na demo pública toca em cinco sítios, e falhar um deles
não dá erro nenhum — dá um prospect a escolher "Logística e Transportes"
e a receber perguntas sobre lugares de subscrição. Foi exactamente o que
aconteceu com a indústria: o passo 1 oferecia-a, a restrição da base não
a conhecia, e quem a escolhia caía no dataset de omissão.

Os cinco sítios:

1. `VERTICALS`, no modelo
2. o CHECK da tabela, que tem de dizer o mesmo que a tupla
3. `flow_content.json`, que é o que o passo 1 mostra
4. `curated_content.json`, nos três idiomas
5. o mapa espanhol, completo

Nada aqui toca na base nem na rede: são os ficheiros do repositório.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.demo_content import VERTICALS, DemoDataset
from src.services import demo_flow_service

RAIZ = Path(__file__).resolve().parents[2]
CURADO = RAIZ / "scripts" / "demo" / "curated_content.json"
FLUXO = RAIZ / "scripts" / "demo" / "flow_content.json"

SECTORES = ("transport", "food")
IDIOMAS = ("pt", "en", "es")


@pytest.fixture(params=SECTORES)
def SECTOR(request):
    return request.param


@pytest.fixture(scope="module")
def datasets():
    doc = json.loads(CURADO.read_text(encoding="utf-8"))
    return doc["datasets"]


def test_a_vertical_existe_na_tupla(SECTOR):
    assert SECTOR in VERTICALS


def test_o_check_da_tabela_diz_o_mesmo_que_a_tupla():
    """A divergência entre os dois é invisível até estar em produção.

    Os testes criam a tabela a partir do modelo e correm em SQLite; o
    cluster corre as migrações em Postgres. Uma vertical que esteja só
    num dos lados passa aqui e falha lá, ou ao contrário — que foi o que
    aconteceu à indústria durante dois meses.
    """
    check = next(
        c for c in DemoDataset.__table__.constraints
        if getattr(c, "name", "") == "demo_datasets_vertical_check"
    )
    texto = str(check.sqltext)
    for v in VERTICALS:
        assert f"'{v}'" in texto, f"{v!r} está em VERTICALS e não está no CHECK"


def test_o_passo_1_oferece_o_sector_nos_tres_idiomas(SECTOR):
    fluxo = json.loads(FLUXO.read_text(encoding="utf-8"))
    entrada = next((v for v in fluxo["verticals"] if v["id"] == SECTOR), None)
    assert entrada is not None, "o sector não aparece no primeiro ecrã da demo"
    for idioma in IDIOMAS:
        assert entrada["label"][idioma].strip()
        assert entrada["hook_markdown"][idioma].strip()


def test_ha_um_dataset_curado_por_idioma(datasets, SECTOR):
    for idioma in IDIOMAS:
        achados = [
            d for d in datasets
            if d["vertical"] == SECTOR and d["locale"] == idioma
        ]
        assert len(achados) == 1, f"{idioma}: esperava 1 dataset, encontrei {len(achados)}"


def test_nenhum_dataset_do_sector_e_o_de_omissao(datasets, SECTOR):
    """Dois predefinidos no mesmo idioma tornam a entrada não-determinista.

    Quem carrega em "Saltar" tem de cair sempre no mesmo sítio, e a
    escolha não pode depender da ordem das linhas na tabela.
    """
    for d in datasets:
        if d["vertical"] == SECTOR:
            assert d["is_default"] is False


def test_o_espanhol_nao_ficou_a_meio(datasets, SECTOR):
    """Meia tradução não se vê até estar à frente de um cliente.

    A verificação é diferencial de propósito: procurar palavras
    espanholas passaria com o texto inglês lá dentro (passa sempre,
    porque há palavras iguais nas duas línguas). O que prova a tradução
    é o espanhol ser DIFERENTE do inglês em todos os campos de texto.
    """
    traduziveis = {
        "name", "description", "agent_name", "title", "summary",
        "label", "question", "answer_markdown",
    }
    en = next(d for d in datasets if d["vertical"] == SECTOR and d["locale"] == "en")
    es = next(d for d in datasets if d["vertical"] == SECTOR and d["locale"] == "es")

    iguais: list[str] = []

    def anda(a, b, caminho=""):
        if isinstance(a, dict):
            for k in a:
                if k in traduziveis and isinstance(a[k], str):
                    if a[k].strip() and a[k] == b.get(k):
                        iguais.append(f"{caminho}.{k}: {a[k][:60]!r}")
                else:
                    anda(a[k], b.get(k, {}), f"{caminho}.{k}")
        elif isinstance(a, list):
            for i, v in enumerate(a):
                if i < len(b):
                    anda(v, b[i], f"{caminho}[{i}]")

    anda(en, es)
    assert not iguais, "campos por traduzir (iguais ao inglês):\n" + "\n".join(iguais)


def test_o_sql_dos_cartoes_fala_das_tabelas_do_sector(datasets, SECTOR):
    """Um cartão com o SQL de outro sector renderiza "—" e não dá erro.

    O `--verify-sql` da curadoria corre o SQL contra a base sintética e
    apanha o que rebenta. Não apanha SQL válido que consulta as tabelas
    erradas — isso só se apanha aqui.
    """
    esquemas = {
        "transport": ("fleet.", "ops.", "freight."),
        "food": ("assortment.", "warehouse.", "trade."),
    }[SECTOR]
    pt = next(d for d in datasets if d["vertical"] == SECTOR and d["locale"] == "pt")

    sqls: list[tuple[str, str]] = []
    for nome, ins in [("insight", pt["insight"])] + [
        (f"extra_insight[{i}]", x) for i, x in enumerate(pt.get("extra_insights", []))
    ]:
        for campo in ("executed_sql", "series_sql"):
            if ins.get(campo):
                sqls.append((f"{nome}.{campo}", ins[campo]))
        for t in ins.get("stat_tiles", []):
            sqls.append((f"{nome}.tile[{t['label']}]", t["value_sql"]))
    for q in pt["qas"]:
        if q.get("executed_sql"):
            sqls.append((f"qa[{q['position']}].executed_sql", q["executed_sql"]))
        for t in q.get("stat_tiles", []):
            sqls.append((f"qa[{q['position']}].tile[{t['label']}]", t["value_sql"]))

    assert sqls, "o dataset não tem SQL nenhum"
    for onde, sql in sqls:
        assert any(e in sql for e in esquemas), f"{onde} não consulta o sector: {sql[:80]!r}"


def test_a_vertical_chega_ao_servico_do_fluxo(SECTOR):
    ids = [v["id"] for v in demo_flow_service.list_verticals("pt")]
    assert SECTOR in ids
