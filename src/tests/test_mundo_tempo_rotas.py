"""Carregador «mundo»: Open-Meteo, AEMET, TomTom, OSRM, regra 561/2006 e postos na rota."""

import datetime as dt
import json
from pathlib import Path

import pytest

from scripts.dados_publicos.mundo import transformar as T

FX = Path(__file__).resolve().parents[2] / "scripts" / "dados_publicos" / "mundo" / "fixtures"


def _j(nome):
    return json.loads((FX / nome).read_text(encoding="utf-8"))


def test_openmeteo_multi_local_por_cidade_e_dia():
    linhas = T.t_openmeteo(_j("openmeteo.json"), ["Badajoz", "Madrid"], None)
    assert len(linhas) == 6
    b = linhas[0]
    assert b["cidade"] == "Badajoz" and b["data"] == dt.date(2026, 10, 10)
    assert b["temp_min"] == 9.2 and b["temp_max"] == 27.3
    assert b["codigo"] == 3 and b["descricao"] == "encoberto"
    assert b["licenca"].startswith("nao-comercial")
    assert {l["cidade"] for l in linhas} == {"Badajoz", "Madrid"}


def test_aemet_fixture_sintetica():
    linhas = T.t_aemet_diaria(_j("aemet_diaria_SINTETICO.json"), "Badajoz", None)
    assert [l["data"] for l in linhas] == [dt.date(2026, 10, 11), dt.date(2026, 10, 12)]
    d1 = linhas[0]
    assert (d1["temp_min"], d1["temp_max"]) == (11.0, 27.0)
    assert d1["vento_max_kmh"] == 15.0 and d1["rajada_max_kmh"] == 30.0
    assert d1["descricao"] == "Poco nuboso" and d1["precipitacao_mm"] is None
    assert linhas[1]["rajada_max_kmh"] is None
    assert "AEMET" in d1["licenca"] and T.licenca_comercial(d1["licenca"])
    # hora do dado = «elaborado» da AEMET (10:12:43 em Madrid, CEST), não a do pedido
    assert d1["actualizado_em"] == dt.datetime(2026, 10, 10, 8, 12, 43, tzinfo=dt.timezone.utc)


def test_openmeteo_com_subscricao_fica_comercial():
    linhas = T.t_openmeteo(
        _j("openmeteo.json"), ["Badajoz", "Madrid"], None, licenca=T.LICENCA_OPENMETEO_CLIENTE
    )
    assert all(T.licenca_comercial(l["licenca"]) for l in linhas)
    assert not T.licenca_comercial(T.LICENCA_OPENMETEO)


def test_tomtom_rota_camiao_com_pausas_e_licenca_comercial():
    r = T.t_tomtom(_j("tomtom_rota_SINTETICO.json"), "Badajoz", "Mérida", None)
    assert r["km"] == 62.2
    assert r["conducao_camiao_min"] == 54.0 and r["pausas_45min"] == 0
    assert r["duracao_camiao_estimada_min"] == 54.0 and r["duracao_carro_min"] is None
    assert T.licenca_comercial(r["licenca"]) and "TomTom" in r["fonte"]
    geo = json.loads(r["geometria_json"])
    assert len(geo) >= 2 and abs(geo[0][0] - 38.88) < 0.05


def test_tomtom_longa_soma_pausa_do_561():
    j = {"routes": [{"summary": {"lengthInMeters": 400000, "travelTimeInSeconds": 300 * 60}}]}
    r = T.t_tomtom(j, "Lisboa", "Madrid", None)
    assert (r["conducao_camiao_min"], r["pausas_45min"], r["duracao_camiao_estimada_min"]) == (
        300.0,
        1,
        345.0,
    )


def test_tomtom_sem_rota_da_erro():
    with pytest.raises(ValueError):
        T.t_tomtom({"routes": []}, "A", "B", None)


def test_perfil_camiao_tomtom():
    p = T.CAMIAO_TOMTOM
    assert p["travelMode"] == "truck" and p["vehicleCommercial"] == "true"
    assert p["vehicleWeight"] == 40000 and p["vehicleHeight"] == 4.0


@pytest.mark.parametrize(
    "km, esperado",
    [
        (65, (48.8, 0, 48.8)),
        (360, (270.0, 0, 270.0)),  # exactamente 4h30: chega sem pausa
        (400, (300.0, 1, 345.0)),
        (625, (468.8, 1, 513.8)),
    ],
)
def test_regra_camiao_80kmh_pausa_45_a_cada_4h30(km, esperado):
    assert T.estimar_camiao(km) == esperado


def test_osrm_rota_com_estimativa_e_licenca_demo():
    r = T.t_osrm(_j("osrm.json"), "Badajoz", "Mérida", None)
    assert 55 < r["km"] < 70
    assert r["pausas_45min"] == 0
    assert r["licenca"] == "demo-nao-comercial" and "TomTom" in r["nota"]
    assert not T.licenca_comercial(r["licenca"])
    geo = json.loads(r["geometria_json"])
    assert len(geo) >= 2 and abs(geo[0][0] - 38.88) < 0.05


def test_postos_perto_da_rota_respeitam_raio_e_km():
    rota = dict(origem="A", destino="B", geometria_json=json.dumps([[38.0, -6.0], [38.0, -5.0]]))
    estacoes = [
        dict(id_estacion=1, lat=38.01, lon=-5.5),  # ~1,1 km da linha, a meio
        dict(id_estacion=2, lat=38.2, lon=-5.5),  # ~22 km: fora
        dict(id_estacion=3, lat=None, lon=None),
    ]
    out = T.postos_perto_de_rotas(estacoes, [rota], raio_km=3)
    rota_osrm = dict(rota, fonte="OSRM demo", licenca="demo-nao-comercial")
    herdado = T.postos_perto_de_rotas(estacoes, [rota_osrm], raio_km=3)
    assert herdado[0]["licenca"] == "demo-nao-comercial" and "OSRM" in herdado[0]["fonte"]
    assert [o["id_estacion"] for o in out] == [1]
    assert out[0]["licenca"] is None  # herda a licença do traçado (aqui não tem)
    assert 0.9 < out[0]["dist_km"] < 1.3
    assert 40 < out[0]["km_desde_origem"] < 48
