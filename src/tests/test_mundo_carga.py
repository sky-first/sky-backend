"""Carregador «mundo»: upsert idempotente, isolamento de falhas e registo em fontes (SQLite, sem rede)."""

import argparse
import datetime as dt
import io
import json
import zipfile
from pathlib import Path

from sqlalchemy import func, select

from scripts.dados_publicos.mundo import carregar as C
from scripts.dados_publicos.mundo import esquema as E
from scripts.dados_publicos.mundo import transformar as T

FX = Path(__file__).resolve().parents[2] / "scripts" / "dados_publicos" / "mundo" / "fixtures"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _s(ref, v):
    return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'


def _n(ref, v):
    return f'<c r="{ref}"><v>{v}</v></c>'


def _xlsx():
    """XLSX mínimo no formato do Weekly Oil Bulletin (strings inline)."""
    cab = (
        _s("A1", "x")
        + _s("B1", "ES_price_with_tax_euro95")
        + _s("C1", "ES_price_with_tax_diesel")
        + _s("D1", "PT_price_with_tax_euro95")
        + _s("E1", "PT_price_with_tax_diesel")
    )
    dados = (
        _n("A4", 46300) + _n("B4", 1550.5) + _n("C4", 1601.2) + _n("D4", 1790) + _n("E4", 1702.9)
    )
    folha = f'<worksheet xmlns="{NS}"><sheetData><row r="1">{cab}</row><row r="4">{dados}</row></sheetData></worksheet>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", folha)
    return b.getvalue()


def test_wob_xlsx_em_euros_por_litro():
    linhas = {l["pais"]: l for l in T.t_wob(_xlsx())}
    assert linhas["ES"]["gasoleo_eur_l"] == 1.601 and linhas["PT"]["gasoleo_eur_l"] == 1.703
    assert linhas["ES"]["data"] == dt.date(2026, 10, 5)


class _Resp:
    def __init__(self, conteudo):
        self.content = conteudo

    def json(self):
        return json.loads(self.content)


def _falso_obter(s, url, timeout=60, **kw):
    if "datex2" in url:
        raise ConnectionError("DGT em baixo (simulado)")
    if "frankfurter" in url:
        return _Resp((FX / "frankfurter.json").read_bytes())
    raise AssertionError(f"pedido inesperado: {url}")


def _args(**kw):
    base = dict(dias_historico=0, semanas_ue=52, festivos_nager=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _motor(tmp_path):
    eng = C.motor(sqlite=str(tmp_path / "m.sqlite"))
    C.criar_esquema(eng)
    return eng


def test_falha_numa_fonte_nao_para_as_outras_e_fica_em_fontes(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "obter", _falso_obter)
    eng = _motor(tmp_path)
    so = {"incidencias", "cambio", "festivos", "portagens", "restricoes"}
    res = {r[0]: r for r in C.correr(eng, so, _args())}
    assert res["incidencias"][3] and "DGT em baixo" in res["incidencias"][3]
    assert res["cambio"][1] == 9 and res["cambio"][3] is None
    assert res["portagens"][3] is None and res["restricoes"][1] == 12
    with eng.connect() as c:
        f = {r.nome: r for r in c.execute(select(E.fontes))}
    assert f["incidencias"].estado == "erro" and "DGT" in f["incidencias"].erro
    assert f["cambio"].estado == "ok" and f["cambio"].linhas == 9 and f["cambio"].uso_comercial
    assert "BCE" in f["cambio"].atribuicao
    assert "tempo" not in f  # fontes fora de --so não são tocadas


def test_upsert_e_idempotente(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "obter", _falso_obter)
    eng = _motor(tmp_path)
    so = {"cambio", "festivos", "portagens", "restricoes"}
    C.correr(eng, so, _args())

    def contagens():
        with eng.connect() as c:
            return {
                t: c.execute(select(func.count()).select_from(E.TABELAS[t])).scalar()
                for t in ("cambio_eur", "festivos", "portagens", "restricoes_pesados", "fontes")
            }

    primeira = contagens()
    C.correr(eng, so, _args())
    assert contagens() == primeira
    assert primeira["cambio_eur"] == 9 and primeira["fontes"] == 4
    with eng.connect() as c:
        a5 = (
            c.execute(
                select(E.portagens.c.preco_eur).where(
                    E.portagens.c.origem == "Badajoz", E.portagens.c.destino == "Madrid"
                )
            )
            .scalars()
            .all()
        )
    assert a5 == [0.0, 0.0, 0.0]


def test_upsert_actualiza_valor_existente(tmp_path):
    eng = _motor(tmp_path)
    linha = dict(data=dt.date(2026, 10, 9), moeda="USD", taxa=1.1, fonte="t")
    with eng.begin() as c:
        C.upsert(c, E.cambio_eur, [linha])
        C.upsert(c, E.cambio_eur, [dict(linha, taxa=1.2)])
    with eng.connect() as c:
        assert c.execute(select(E.cambio_eur.c.taxa)).scalars().all() == [1.2]
