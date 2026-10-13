"""Carregador «mundo» com destino à base partilhada ``sky_world`` (fontes do sistema).

O que se prova (sem rede):
- com ``--mundo-partilhado`` a TomTom não é chamada nem guardada (termos por
  confirmar) — só com ``--guardar-rotas-tomtom``;
- linhas não-comerciais e o traçado das rotas saem da base partilhada;
- combinações perigosas são recusadas à entrada;
- uma fotografia parcial do MITECO não apaga os postos que faltam (S12).
"""

import argparse
import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from scripts.dados_publicos.mundo import carregar as C
from scripts.dados_publicos.mundo import esquema as E
from scripts.dados_publicos.mundo import transformar as T

FX = Path(__file__).resolve().parents[2] / "scripts" / "dados_publicos" / "mundo" / "fixtures"
CHAVES = ("AEMET_API_KEY", "OPEN_METEO_API_KEY", "TOMTOM_API_KEY", "MUNDO_PARTILHADO")


class _Resp:
    def __init__(self, conteudo):
        self.content = conteudo

    def json(self):
        return json.loads(self.content)


def _args(**kw):
    base = dict(
        dias_historico=0,
        semanas_ue=52,
        permitir_nao_comercial=False,
        mundo_partilhado=False,
        guardar_rotas_tomtom=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def eng(tmp_path, monkeypatch):
    for k in CHAVES + ("KUBERNETES_SERVICE_HOST",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(C.time, "sleep", lambda *_: None)
    e = C.motor(sqlite=str(tmp_path / "m.sqlite"))
    C.criar_esquema(e)
    return e


def _fontes(eng):
    with eng.connect() as c:
        return {r.nome: r for r in c.execute(select(E.fontes))}


def _contar(eng, tabela):
    with eng.connect() as c:
        return c.execute(select(func.count()).select_from(tabela)).scalar()


def _semear_osrm_antigo(eng):
    with eng.begin() as c:
        C.upsert(
            c,
            E.rotas_referencia,
            [
                T.t_osrm(
                    json.loads((FX / "osrm.json").read_text(encoding="utf-8")),
                    "Badajoz",
                    "Mérida",
                    None,
                )
            ],
        )


def test_mundo_partilhado_nao_chama_nem_guarda_tomtom(eng, monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "tt")
    pedidos = []
    monkeypatch.setattr(C, "obter", lambda *a, **k: pedidos.append(a) or None)
    res = {r[0]: r for r in C.correr(eng, {"rotas"}, _args(mundo_partilhado=True))}
    assert pedidos == []
    assert res["rotas"][5] == "termos_por_confirmar"
    f = _fontes(eng)["rotas"]
    assert f.estado == "termos_por_confirmar" and "TomTom" in f.erro
    assert _contar(eng, E.rotas_referencia) == 0


def test_mundo_partilhado_com_termos_confirmados_guarda(eng, monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "tt")
    monkeypatch.setattr(
        C, "obter", lambda *a, **k: _Resp((FX / "tomtom_rota_SINTETICO.json").read_bytes())
    )
    res = {
        r[0]: r
        for r in C.correr(eng, {"rotas"}, _args(mundo_partilhado=True, guardar_rotas_tomtom=True))
    }
    assert res["rotas"][5] == "ok"
    assert _contar(eng, E.rotas_referencia) == len(T.ROTAS_DEMO)


def test_fora_do_mundo_partilhado_nada_muda(eng, monkeypatch):
    """A demo (`--esquema ops`) continua como estava: TomTom com chave grava."""
    monkeypatch.setenv("TOMTOM_API_KEY", "tt")
    monkeypatch.setattr(
        C, "obter", lambda *a, **k: _Resp((FX / "tomtom_rota_SINTETICO.json").read_bytes())
    )
    res = {r[0]: r for r in C.correr(eng, {"rotas"}, _args())}
    assert res["rotas"][5] == "ok"


def test_preparar_retira_nao_comerciais_e_tracado(eng):
    _semear_osrm_antigo(eng)  # licenca demo-nao-comercial
    with eng.begin() as c:
        C.upsert(
            c,
            E.cambio_eur,
            [
                {"data": dt.date(2026, 10, 1), "moeda": "USD", "taxa": 1.1, "fonte": "x"},
                {
                    "data": dt.date(2026, 10, 2),
                    "moeda": "USD",
                    "taxa": 1.2,
                    "fonte": "x",
                    "licenca": "nao-comercial (teste)",
                },
            ],
        )
    apagadas = C.preparar_mundo_partilhado(eng, _args(mundo_partilhado=True))
    assert apagadas["rotas_referencia"] == 1
    assert apagadas["cambio_eur"] == 1
    assert _contar(eng, E.rotas_referencia) == 0
    assert _contar(eng, E.cambio_eur) == 1  # a comercial fica


@pytest.mark.parametrize(
    "extra",
    [
        ["--permitir-nao-comercial"],
        ["--esquema", "ops"],
        ["--demo"],
    ],
)
def test_main_recusa_combinacoes_perigosas(tmp_path, monkeypatch, extra):
    for k in CHAVES + ("KUBERNETES_SERVICE_HOST",):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit) as e:
        C.main(["--sqlite", str(tmp_path / "m.sqlite"), "--mundo-partilhado", *extra])
    assert e.value.code == 2


def test_main_mundo_partilhado_por_variavel_de_ambiente(tmp_path, monkeypatch):
    for k in CHAVES + ("KUBERNETES_SERVICE_HOST",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MUNDO_PARTILHADO", "true")
    monkeypatch.setenv("TOMTOM_API_KEY", "tt")
    monkeypatch.setattr(C, "obter", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rede")))
    rc = C.main(["--sqlite", str(tmp_path / "m.sqlite"), "--so", "rotas"])
    assert rc == 0  # termos por confirmar não é erro


def test_mundo_fotografia_parcial_nao_apaga(eng, monkeypatch):
    """S12 — o MITECO devolve meia fotografia: ficam os postos anteriores."""
    mit = json.loads((FX / "miteco_actual.json").read_text(encoding="utf-8"))
    base, fecha = T.t_miteco_actual(mit)

    def _postos(n):
        return [dict(base[i % len(base)], id_estacion=100000 + i) for i in range(n)]

    monkeypatch.setattr(C, "obter", lambda *a, **k: _Resp(json.dumps(mit).encode()))
    monkeypatch.setattr(T, "t_miteco_actual", lambda j: (_postos(2000), fecha))
    C.correr(eng, {"gasolineras"}, _args())
    assert _contar(eng, E.gasolineras_precio) == 2000
    dado_antes = _fontes(eng)["gasolineras"].dado_de

    monkeypatch.setattr(T, "t_miteco_actual", lambda j: (_postos(1200), fecha))
    C.correr(eng, {"gasolineras"}, _args())
    f = _fontes(eng)["gasolineras"]
    assert f.estado == "erro" and "parcial" in f.erro
    assert _contar(eng, E.gasolineras_precio) == 2000
    assert f.dado_de == dado_antes
