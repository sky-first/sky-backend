"""Carregador «mundo»: DGT DATEX II v3.7 (XML) → linhas, sem rede."""

import datetime as dt
from pathlib import Path

from scripts.dados_publicos.mundo import transformar as T

FX = Path(__file__).resolve().parents[2] / "scripts" / "dados_publicos" / "mundo" / "fixtures"


def _linhas():
    return T.t_datex((FX / "datex2.xml").read_bytes())


def test_publication_time_em_utc_em_todas_as_linhas():
    linhas, pub = _linhas()
    assert pub == dt.datetime(2026, 10, 10, 20, 16, 10, 265000, tzinfo=dt.timezone.utc)
    assert len(linhas) == 2
    assert all(l["actualizado_em"] == pub for l in linhas)


def test_registo_linear_usa_ponto_from_e_pk_fim_do_to():
    l = {x["id"]: x for x in _linhas()[0]}["18811074"]
    assert l["tipo"] == "RoadOrCarriagewayOrLaneManagement"
    assert l["subtipo"] == "narrowLanes"
    assert l["causa"] == "roadMaintenance" and l["causa_detalhe"] == "roadworks"
    assert l["carretera"] == "N-400"
    assert l["pk"] == 37.1 and l["pk_fim"] == 37.3
    assert l["municipio"] == "Ontígola" and l["provincia"] == "Toledo"
    assert abs(l["lat"] - 39.993732) < 1e-6
    assert l["inicio"] == dt.datetime(2025, 12, 12, 7, 5, 19, tzinfo=dt.timezone.utc)
    assert l["fim"] is None and l["estado"] == "active" and l["activa"] is True


def test_gravidade_herdada_da_situacao_e_ponto_simples():
    l = {x["id"]: x for x in _linhas()[0]}["16676270"]
    assert l["gravidade"] == "highest"
    assert l["carretera"] == "HU-883" and l["pk"] == 1.2 and l["pk_fim"] is None
    assert l["subtipo"] == "roadClosed"


def test_prefixos_de_namespace_diferentes_nao_partem_o_parser():
    xml = (
        (FX / "datex2.xml")
        .read_bytes()
        .replace(b"sit:", b"zz:")
        .replace(b"xmlns:sit=", b"xmlns:zz=")
    )
    linhas, _ = T.t_datex(xml)
    assert {l["id"] for l in linhas} == {"18811074", "16676270"}
