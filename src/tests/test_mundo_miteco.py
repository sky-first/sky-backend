"""Carregador «mundo»: transformação MITECO (actual + histórico) sem rede."""

import datetime as dt
import json
from pathlib import Path

from scripts.dados_publicos.mundo import transformar as T

FX = Path(__file__).resolve().parents[2] / "scripts" / "dados_publicos" / "mundo" / "fixtures"


def _j(nome):
    return json.loads((FX / nome).read_text(encoding="utf-8"))


def test_actual_converte_virgulas_coordenadas_e_hora_madrid_para_utc():
    linhas, fecha = T.t_miteco_actual(_j("miteco_actual.json"))
    # "10/10/2026 22:17:04" em Madrid (CEST, UTC+2) → 20:17:04 UTC
    assert fecha == dt.datetime(2026, 10, 10, 20, 17, 4, tzinfo=dt.timezone.utc)
    assert len(linhas) == 5
    por_id = {l["id_estacion"]: l for l in linhas}
    repsol = por_id[7550]
    assert repsol["precio_gasoleo_a"] == 1.995
    assert isinstance(repsol["lat"], float) and 38 < repsol["lat"] < 39
    assert repsol["lon"] < 0
    assert repsol["carretera"] == "N-435" and repsol["pk"] == 22.5
    assert repsol["actualizado_em"] == fecha
    # preço vazio vira NULL, não 0
    assert por_id[7612]["precio_gasoleo_a"] is None
    assert por_id[12402]["precio_gasoleo_b"] == 1.477


def test_morada_com_nacional_em_numeracao_romana():
    assert T.extrair_carretera("CARRETERA N-V MADRID-LISBOA, KM 395, 7 KM. ") == ("N-V", 395.0)
    assert T.extrair_carretera("PLAZA DE LA IGLESIA, S/N") == (None, None)
    assert T.extrair_carretera("AUTOVIA A-5 KM 340") == ("A-5", 340.0)
    assert T.extrair_carretera("C-423 km 40,6") == ("C-423", 40.6)


def test_historico_agrega_por_provincia_e_total_espanha():
    linhas = T.t_miteco_hist(_j("miteco_hist.json"), dt.date(2026, 10, 9))
    por = {l["provincia"]: l for l in linhas}
    assert set(por) == {"BADAJOZ", "MADRID", "ESPAÑA"}
    bad = por["BADAJOZ"]
    assert bad["n_postos"] == 3
    assert bad["minimo"] == 1.749 and bad["maximo"] == 1.959 and bad["mediana"] == 1.939
    assert bad["origem"] == "historico" and bad["data"] == dt.date(2026, 10, 9)
    assert por["ESPAÑA"]["n_postos"] == 5


def test_agregado_ignora_precos_nulos_e_zero():
    linhas = T.agregar_gasoleo(
        [("x", None), ("x", 0), ("x", 1.5)], dt.date(2026, 1, 1), "actual", "f"
    )
    assert {l["provincia"]: l["n_postos"] for l in linhas} == {"X": 1, "ESPAÑA": 1}
