"""Carregador «mundo»: fontes pagas (AEMET, Open-Meteo com subscrição, TomTom).

Sem rede: `obter` é trocado por um falso que serve fixtures e regista cada
pedido. O que se prova:
- sem chave, nada é chamado, `fontes.estado = sem_chave` e as linhas
  anteriores ficam com a sua licença;
- com chave, só se chamam os endpoints comerciais (nunca api.open-meteo.com
  nem router.project-osrm.org);
- a chave nunca fica gravada em `fontes.erro`;
- o modo não-comercial só existe por flag e é recusado dentro do Kubernetes.
"""

import argparse
import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, Table, Text, inspect, select

from scripts.dados_publicos.mundo import carregar as C
from scripts.dados_publicos.mundo import esquema as E
from scripts.dados_publicos.mundo import transformar as T

FX = Path(__file__).resolve().parents[2] / "scripts" / "dados_publicos" / "mundo" / "fixtures"
CHAVES = ("AEMET_API_KEY", "OPEN_METEO_API_KEY", "TOMTOM_API_KEY")


class _Resp:
    def __init__(self, conteudo):
        self.content = conteudo

    def json(self):
        return json.loads(self.content)


class _Rede:
    """Falso `obter`: responde por URL e guarda (url, params, headers)."""

    def __init__(self, falhar=None):
        self.pedidos = []
        self.falhar = falhar

    def __call__(self, s, url, timeout=60, **kw):
        self.pedidos.append((url, kw.get("params") or {}, kw.get("headers") or {}))
        if self.falhar and self.falhar in url:
            raise ConnectionError(f"401 Client Error for url: {url}?key={kw['params'].get('key')}")
        if "opendata.aemet.es" in url and "/datos/" not in url:
            cod = url.rsplit("/", 1)[-1]
            return _Resp(
                json.dumps(
                    {"estado": 200, "datos": f"https://opendata.aemet.es/opendata/sh/datos/{cod}"}
                ).encode()
            )
        if "/sh/datos/" in url:
            # a AEMET devolve ISO-8859-15 sem o declarar
            txt = (FX / "aemet_diaria_SINTETICO.json").read_text(encoding="utf-8")
            return _Resp(txt.encode("iso-8859-15"))
        if "customer-api.open-meteo.com" in url:
            pedidas = (kw["params"]["latitude"]).count(",") + 1
            base = json.loads((FX / "openmeteo.json").read_text(encoding="utf-8"))
            return _Resp(json.dumps([base[0]] * pedidas).encode())
        if "api.tomtom.com" in url:
            return _Resp((FX / "tomtom_rota_SINTETICO.json").read_bytes())
        raise AssertionError(f"pedido inesperado: {url}")

    def urls(self):
        return [u for u, _, _ in self.pedidos]


def _args(**kw):
    base = dict(dias_historico=0, semanas_ue=52, permitir_nao_comercial=False)
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


def _linhas(eng, tabela):
    with eng.connect() as c:
        return [dict(r._mapping) for r in c.execute(select(tabela))]


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


# ── sem chave ────────────────────────────────────────────────────────────────


def test_sem_chaves_tempo_e_rotas_nao_chamam_nada(eng, monkeypatch):
    rede = _Rede()
    monkeypatch.setattr(C, "obter", rede)
    _semear_osrm_antigo(eng)
    res = {r[0]: r for r in C.correr(eng, {"tempo", "rotas"}, _args())}
    assert rede.pedidos == []
    assert res["tempo"][5] == "sem_chave" and res["rotas"][5] == "sem_chave"
    f = _fontes(eng)
    assert f["tempo"].estado == "sem_chave" and "OPEN_METEO_API_KEY" in f["tempo"].erro
    assert f["rotas"].estado == "sem_chave" and "TOMTOM_API_KEY" in f["rotas"].erro
    # as linhas antigas ficam, com a licença delas, e a fonte diz que não são comerciais
    rotas = _linhas(eng, E.rotas_referencia)
    assert len(rotas) == 1 and rotas[0]["licenca"] == "demo-nao-comercial"
    assert f["rotas"].uso_comercial is False
    assert f["tempo"].uso_comercial is None  # tabela vazia: nada a dizer


def test_main_sem_chaves_sai_com_zero(tmp_path, monkeypatch):
    for k in CHAVES + ("KUBERNETES_SERVICE_HOST",):
        monkeypatch.delenv(k, raising=False)
    rede = _Rede()
    monkeypatch.setattr(C, "obter", rede)
    rc = C.main(["--sqlite", str(tmp_path / "m.sqlite"), "--so", "tempo", "--so", "rotas"])
    assert rc == 0 and rede.pedidos == []


def test_chave_vazia_conta_como_ausente(eng, monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "  ")
    rede = _Rede()
    monkeypatch.setattr(C, "obter", rede)
    res = {r[0]: r for r in C.correr(eng, {"rotas"}, _args())}
    assert res["rotas"][5] == "sem_chave" and rede.pedidos == []


# ── tempo com chave ──────────────────────────────────────────────────────────


def test_tempo_aemet_e_open_meteo_cliente(eng, monkeypatch):
    monkeypatch.setenv("AEMET_API_KEY", "aemet-segredo")
    monkeypatch.setenv("OPEN_METEO_API_KEY", "om-segredo")
    rede = _Rede()
    monkeypatch.setattr(C, "obter", rede)
    res = {r[0]: r for r in C.correr(eng, {"tempo"}, _args())}
    assert res["tempo"][5] == "ok", res["tempo"]
    assert not any(u.startswith(C.OPENMETEO_GRATIS) for u in rede.urls())
    # AEMET: chave no cabeçalho, não no URL
    aemet = [(u, h) for u, _, h in rede.pedidos if "/municipio/diaria/" in u]
    assert len(aemet) == len(T.AEMET_MUNICIPIOS)
    assert all(h.get("api_key") == "aemet-segredo" and "segredo" not in u for u, h in aemet)
    # Open-Meteo de cliente só para as cidades que a AEMET não cobre (PT)
    om = [p for u, p, _ in rede.pedidos if "customer-api.open-meteo.com" in u]
    assert len(om) == 1 and om[0]["apikey"] == "om-segredo"
    assert om[0]["latitude"].count(",") + 1 == len(T.CIDADES) - len(T.AEMET_MUNICIPIOS)
    linhas = _linhas(eng, E.tempo_cidades)
    por_cidade = {l["cidade"]: l["licenca"] for l in linhas}
    assert set(por_cidade) == set(T.CIDADES)
    assert "AEMET" in por_cidade["Badajoz"] and "customer-api" in por_cidade["Lisboa"]
    assert all(T.licenca_comercial(l) for l in por_cidade.values())
    f = _fontes(eng)["tempo"]
    assert f.estado == "ok" and f.uso_comercial is True
    # dado_de = «elaborado» da AEMET (mais recente que o pedido? não: é a hora da AEMET)
    assert f.dado_de is not None


def test_tempo_so_aemet_deixa_pt_por_actualizar(eng, monkeypatch):
    monkeypatch.setenv("AEMET_API_KEY", "k")
    rede = _Rede()
    monkeypatch.setattr(C, "obter", rede)
    C.correr(eng, {"tempo"}, _args())
    assert not any("open-meteo" in u for u in rede.urls())
    cidades = {l["cidade"] for l in _linhas(eng, E.tempo_cidades)}
    assert cidades == set(T.AEMET_MUNICIPIOS)


def test_tempo_so_open_meteo_cliente(eng, monkeypatch):
    monkeypatch.setenv("OPEN_METEO_API_KEY", "om")
    rede = _Rede()
    monkeypatch.setattr(C, "obter", rede)
    C.correr(eng, {"tempo"}, _args())
    assert rede.urls() == [C.OPENMETEO_CLIENTE]
    assert {l["cidade"] for l in _linhas(eng, E.tempo_cidades)} == set(T.CIDADES)


# ── rotas com chave ──────────────────────────────────────────────────────────


def test_rotas_tomtom_perfil_camiao_substitui_osrm(eng, monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "tt")
    rede = _Rede()
    monkeypatch.setattr(C, "obter", rede)
    _semear_osrm_antigo(eng)
    res = {r[0]: r for r in C.correr(eng, {"rotas"}, _args())}
    assert res["rotas"][5] == "ok" and res["rotas"][1] == len(T.ROTAS_DEMO)
    assert all("api.tomtom.com/routing/1/calculateRoute/" in u for u in rede.urls())
    assert not any("project-osrm" in u for u in rede.urls())
    p = rede.pedidos[0][1]
    assert p["key"] == "tt" and p["travelMode"] == "truck" and p["vehicleCommercial"] == "true"
    assert p["vehicleWeight"] == 40000
    rotas = _linhas(eng, E.rotas_referencia)
    assert all(T.licenca_comercial(r["licenca"]) for r in rotas)
    assert _fontes(eng)["rotas"].uso_comercial is True


def test_chave_nao_fica_gravada_no_erro(eng, monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "super-segredo-123")
    monkeypatch.setattr(C, "obter", _Rede(falhar="api.tomtom.com"))
    C.correr(eng, {"rotas"}, _args())
    f = _fontes(eng)["rotas"]
    assert f.estado == "erro" and "super-segredo-123" not in f.erro and "key=***" in f.erro


def test_gasolineras_rota_herda_licenca_nao_comercial_do_tracado(eng, monkeypatch):
    _semear_osrm_antigo(eng)
    mit = json.loads((FX / "miteco_actual.json").read_text(encoding="utf-8"))
    linhas, fecha = T.t_miteco_actual(mit)
    monkeypatch.setattr(C, "obter", lambda *a, **k: _Resp(json.dumps(mit).encode()))
    monkeypatch.setattr(T, "t_miteco_actual", lambda j: (linhas * 1000, fecha))
    C.correr(eng, {"gasolineras"}, _args())
    f = _fontes(eng)["gasolineras"]
    assert f.estado == "ok", f.erro
    assert f.uso_comercial is False  # o traçado ainda é OSRM
    assert all(
        l["licenca"] == "MITECO — reutilização (Lei 37/2007, RD 1495/2011)"
        for l in _linhas(eng, E.gasolineras_precio)
    )


# ── modo não-comercial ───────────────────────────────────────────────────────


def test_flag_nao_comercial_recusada_no_kubernetes(tmp_path, monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    with pytest.raises(SystemExit):
        C.main(["--sqlite", str(tmp_path / "m.sqlite"), "--permitir-nao-comercial"])


def test_flag_nao_comercial_marca_licenca(eng, monkeypatch):
    urls = []

    def falso(s, url, timeout=60, **kw):
        urls.append(url)
        if "project-osrm" in url:
            return _Resp((FX / "osrm.json").read_bytes())
        if "api.open-meteo.com" in url:
            n = kw["params"]["latitude"].count(",") + 1
            base = json.loads((FX / "openmeteo.json").read_text(encoding="utf-8"))
            return _Resp(json.dumps([base[0]] * n).encode())
        raise AssertionError(url)

    monkeypatch.setattr(C, "obter", falso)
    C.correr(eng, {"rotas", "tempo"}, _args(permitir_nao_comercial=True))
    f = _fontes(eng)
    assert f["rotas"].uso_comercial is False and f["tempo"].uso_comercial is False
    assert "--permitir-nao-comercial" in f["rotas"].licenca
    assert all(not T.licenca_comercial(l["licenca"]) for l in _linhas(eng, E.tempo_cidades))


# ── esquema ──────────────────────────────────────────────────────────────────


def test_colunas_novas_chegam_a_tabelas_antigas(tmp_path):
    e = C.motor(sqlite=str(tmp_path / "velho.sqlite"))
    velho = MetaData()
    Table(
        "cambio_eur",
        velho,
        Column("data", Text, primary_key=True),
        Column("moeda", Text, primary_key=True),
    )
    with e.begin() as c:
        velho.create_all(c)
    C.criar_esquema(e)
    with e.connect() as c:
        cols = {x["name"] for x in inspect(c).get_columns("cambio_eur")}
    assert {"taxa", "fonte", "licenca"} <= cols
    with e.begin() as c:
        C.upsert(
            c, E.cambio_eur, [dict(data=dt.date(2026, 10, 9), moeda="USD", taxa=1.1, fonte="t")]
        )
    assert _linhas(e, E.cambio_eur)[0]["licenca"].startswith("BCE")


def test_festivos_apaga_restos_do_nager(eng, monkeypatch):
    with eng.begin() as c:
        C.upsert(
            c,
            E.festivos,
            [
                dict(
                    chave="ES|NAC|2026-11-01",
                    data=dt.date(2026, 11, 1),
                    pais="ES",
                    fonte="Nager.Date v3 (fallback)",
                    licenca="nao-comercial",
                )
            ],
        )
    C.correr(eng, {"festivos"}, _args())
    linhas = _linhas(eng, E.festivos)
    assert linhas and not any("Nager" in (l["fonte"] or "") for l in linhas)
    assert all(T.licenca_comercial(l["licenca"]) for l in linhas)
    assert _fontes(eng)["festivos"].uso_comercial is True


def test_sem_segredos():
    assert (
        C.sem_segredos("x?apikey=abc&b=1 key=zz api_key=q")
        == "x?apikey=***&b=1 key=*** api_key=***"
    )
