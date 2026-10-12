"""Carregador «mundo»: feriados oficiais (BOE / DRE, sem Nager) e câmbios BCE."""

import datetime as dt
import json
from pathlib import Path

import pytest

from scripts.dados_publicos.mundo import referencia as R
from scripts.dados_publicos.mundo import transformar as T

FX = Path(__file__).resolve().parents[2] / "scripts" / "dados_publicos" / "mundo" / "fixtures"


def _fer():
    return {l["chave"]: l for l in R.festivos_oficiais()}


def test_feriados_oficiais_es_2026_trasladacoes_por_regiao():
    f = _fer()
    assert f["ES|NAC|2026-10-12"]["nome"] == "Fiesta Nacional de España"
    assert f["ES|NAC|2026-10-12"]["regiao"] is None
    # 01/11/2026 e 06/12/2026 são domingo: o BOE traslada para segunda onde a CCAA quis
    for reg in ("ES-EX", "ES-MD", "ES-AN"):
        assert f[f"ES|{reg}|2026-11-02"]["dia_semana"] == "seg"
        assert f[f"ES|{reg}|2026-12-07"]["dia_semana"] == "seg"
    assert "ES|ES-CT|2026-11-02" not in f  # Cataluña não trasladou
    assert "ES|NAC|2026-11-01" not in f
    assert f["ES|ES-EX|2026-09-08"]["nome"] == "Día de Extremadura"
    assert f["ES|ES-CT|2026-09-11"]["nome"] == "Fiesta Nacional de Cataluña"
    es_2026 = [l for k, l in f.items() if k.startswith("ES|") and "|2026-" in k]
    assert all("BOE-A-2025-21667" in l["fonte"] for l in es_2026)
    assert all(l["licenca"].startswith("BOE — Licencia tipo BOE") for l in es_2026)


def test_feriados_es_2026_doze_por_territorio_como_no_boe():
    nac = sum(1 for k in _fer() if k.startswith("ES|NAC|2026"))
    assert nac == 7
    for reg in R.CCAA:
        n = sum(1 for k in _fer() if k.startswith(f"ES|{reg}|2026"))
        # Canarias: 11 no anexo + 1 festivo insular (nota do BOE, por ilha)
        assert nac + n == (11 if reg == "ES-CN" else 12), reg
    assert "insular" in _fer()["ES|ES-CN|2026-05-30"]["nota"]


def test_feriados_es_2027_provisorios_sem_regionais():
    f = _fer()
    es = {k: l for k, l in f.items() if k.startswith("ES|") and "|2027-" in k}
    assert all(k.startswith("ES|NAC|") for k in es)
    assert f["ES|NAC|2027-10-12"]["nome"] == "Fiesta Nacional de España"
    assert f["ES|NAC|2027-03-26"]["nome"] == "Viernes Santo"  # Páscoa 28/03/2027 − 2
    assert all("Provisório" in l["nota"] for l in es.values())
    assert all("por publicar" in l["fonte"] for l in es.values())
    assert "domingo" in f["ES|NAC|2027-08-15"]["nota"]


def test_feriados_pt_moveis_calculados_da_pascoa():
    f = _fer()
    assert f["PT|NAC|2026-06-04"]["nome"] == "Corpo de Deus"  # Páscoa 05/04/2026 + 60
    assert f["PT|NAC|2027-05-27"]["nome"] == "Corpo de Deus"  # Páscoa 28/03/2027 + 60
    assert f["PT|NAC|2026-04-03"]["nome"] == "Sexta-feira Santa"
    assert f["PT|NAC|2027-03-26"]["nome"] == "Sexta-feira Santa"
    assert f["PT|NAC|2026-12-08"]["nome"] == "Imaculada Conceição"
    assert f["PT|NAC|2027-12-08"]["nome"] == "Imaculada Conceição"
    for ano in (2026, 2027):
        assert sum(1 for k in f if k.startswith(f"PT|NAC|{ano}")) == 13
    pt = [l for l in f.values() if l["pais"] == "PT"]
    assert all(l["fonte"].startswith("DRE") and l["licenca"].startswith("DRE") for l in pt)


@pytest.mark.parametrize(
    "ano, dia",
    [
        (2024, dt.date(2024, 3, 31)),
        (2026, dt.date(2026, 4, 5)),
        (2027, dt.date(2027, 3, 28)),
        (2028, dt.date(2028, 4, 16)),
        (2038, dt.date(2038, 4, 25)),
        (2285, dt.date(2285, 3, 22)),
    ],
)
def test_pascoa_gregoriana(ano, dia):
    assert R.pascoa(ano) == dia


def test_feriados_anos_seguintes_calculados():
    f = {l["chave"]: l for l in R.festivos_oficiais([2028])}
    assert f["PT|NAC|2028-04-14"]["nome"] == "Sexta-feira Santa"
    assert f["ES|NAC|2028-04-14"]["nome"] == "Viernes Santo"


def test_sem_nager_no_carregador():
    from scripts.dados_publicos.mundo import carregar as C

    assert not hasattr(T, "t_nager") and not hasattr(C, "NAGER")
    assert not (FX / "nager_es.json").exists()


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
