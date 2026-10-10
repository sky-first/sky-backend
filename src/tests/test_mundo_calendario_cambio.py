"""Carregador «mundo»: feriados (tabela oficial + fallback Nager) e câmbios BCE."""

import datetime as dt
import json
from pathlib import Path

from scripts.dados_publicos.mundo import referencia as R
from scripts.dados_publicos.mundo import transformar as T

FX = Path(__file__).resolve().parents[2] / "scripts" / "dados_publicos" / "mundo" / "fixtures"


def test_feriados_oficiais_es_2026_trasladacoes_por_regiao():
    f = {l["chave"]: l for l in R.festivos_oficiais()}
    assert f["ES|NAC|2026-10-12"]["nome"] == "Fiesta Nacional de España"
    # 01/11/2026 é domingo: o BOE traslada para segunda 02/11 em EX, MD, AN
    for reg in ("ES-EX", "ES-MD", "ES-AN"):
        assert f[f"ES|{reg}|2026-11-02"]["dia_semana"] == "seg"
        assert f[f"ES|{reg}|2026-12-07"]["dia_semana"] == "seg"
    assert "ES|NAC|2026-11-01" not in f
    assert f["ES|ES-EX|2026-09-08"]["nome"] == "Día de Extremadura"
    es_2026 = [l for k, l in f.items() if k.startswith("ES|") and "|2026-" in k]
    assert all("BOE-A-2025-21667" in l["fonte"] for l in es_2026)
    assert all(l["licenca"].startswith("oficial") for l in f.values())


def test_feriados_pt_moveis_calculados_da_pascoa():
    f = {l["chave"]: l for l in R.festivos_oficiais()}
    assert f["PT|NAC|2026-06-04"]["nome"] == "Corpo de Deus"  # Páscoa 05/04/2026 + 60
    assert f["PT|NAC|2027-05-27"]["nome"] == "Corpo de Deus"  # Páscoa 28/03/2027 + 60
    assert f["PT|NAC|2026-04-03"]["nome"] == "Sexta-feira Santa"
    assert sum(1 for k in f if k.startswith("PT|NAC|2026")) == 13


def test_nager_fallback_marca_licenca_nao_comercial_e_regiao():
    lst = json.loads((FX / "nager_es.json").read_text(encoding="utf-8"))
    linhas = {l["chave"]: l for l in T.t_nager(lst, "ES")}
    assert linhas["ES|NAC|2026-10-12"]["regiao"] is None
    assert linhas["ES|ES-AN|2026-02-28"]["regiao"] == "ES-AN"
    assert "domingo" in linhas["ES|NAC|2026-11-01"]["nota"]
    assert all(l["licenca"] == "nao-comercial" for l in linhas.values())


def test_frankfurter_serie_temporal_em_linhas():
    j = json.loads((FX / "frankfurter.json").read_text(encoding="utf-8"))
    linhas = T.t_frankfurter(j)
    assert len(linhas) == 9  # 3 dias × 3 moedas
    usd = {l["data"]: l["taxa"] for l in linhas if l["moeda"] == "USD"}
    assert usd[dt.date(2026, 10, 9)] == 1.1206
    assert all(isinstance(l["taxa"], float) for l in linhas)


def test_frankfurter_formato_latest():
    linhas = T.t_frankfurter({"base": "EUR", "date": "2026-10-09", "rates": {"USD": 1.12}})
    assert linhas == [
        dict(data=dt.date(2026, 10, 9), moeda="USD", taxa=1.12, fonte="BCE via Frankfurter")
    ]
