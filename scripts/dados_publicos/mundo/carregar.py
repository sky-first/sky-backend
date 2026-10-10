# -*- coding: utf-8 -*-
"""
Orquestração: descarrega cada fonte, transforma, faz upsert por chave natural
e regista o resultado em ``mundo.fontes``. Cada fonte corre isolada: se uma
falhar, as outras continuam e o erro fica em ``mundo.fontes.erro``.
"""

import argparse
import datetime as dt
import logging
import os
import sys
import time
import traceback

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import create_engine, delete, select, text, update
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.dialects import sqlite as sqlite_dialect
from urllib3.util.retry import Retry

from . import esquema as E
from . import referencia as R
from . import transformar as T

log = logging.getLogger("mundo")
UA = {"User-Agent": "SkyFirst-mundo/1.0 (+https://skyfirstlabs.com)"}

MITECO = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes"
DGT = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml"
NAGER = "https://date.nager.at/api/v3/PublicHolidays/{ano}/{pais}"
FRANKFURTER = ["https://api.frankfurter.dev/v1", "https://api.frankfurter.app"]
OPENMETEO = "https://api.open-meteo.com/v1/forecast"
AEMET = "https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio/diaria/{cod}"
OSRM = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
WOB = (
    "https://energy.ec.europa.eu/document/download/906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
    "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx"
)

# nome → metadados para mundo.fontes (licença e atribuição: DADOS_EXTERNOS_COMERCIAL_2026-10.md)
CATALOGO = {
    "rotas": dict(
        descricao="Distância e duração origem–destino (rotas da demo) + estimativa camião Reg. 561/2006",
        url="https://router.project-osrm.org",
        licenca="demo-nao-comercial: OSRM demo «reasonable, non-commercial use», máx. 1 pedido/s; dados OSM ODbL. "
        "Produção: TomTom Routing (perfil camião, 20.000 rotas/mês grátis, comercial) ou OSRM alojado",
        uso_comercial=False,
        atribuicao="© OpenStreetMap contributors (ODbL)",
        frequencia="mensal (rede viária muda pouco)",
    ),
    "gasolineras": dict(
        descricao="Preço actual por posto em Espanha (MITECO Geoportal) + postos a ≤5 km das rotas",
        url=MITECO + "/EstacionesTerrestres/",
        licenca="Reutilização sem autorização expressa (Lei 37/2007, RD 1495/2011; aviso legal MITECO)",
        uso_comercial=True,
        atribuicao="Fuente: Ministerio para la Transición Ecológica (Geoportal de Gasolineras). "
        "Não alterar a data de actualização; não insinuar patrocínio",
        frequencia="30 min",
    ),
    "gasoleo_historico": dict(
        descricao="Gasóleo A por província e dia (histórico MITECO + fotografia do dia)",
        url=MITECO + "/EstacionesTerrestresHist/FiltroProducto/{dd-mm-aaaa}/4",
        licenca="Idem MITECO",
        uso_comercial=True,
        atribuicao="Fuente: Ministerio para la Transición Ecológica",
        frequencia="diária (01:00)",
    ),
    "gasoleo_ue": dict(
        descricao="Médias nacionais semanais ES/PT/UE com impostos (Weekly Oil Bulletin)",
        url="https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en",
        licenca="Reutilização permitida com citação da fonte (Comissão Europeia, Decisão 2011/833/UE)",
        uso_comercial=True,
        atribuicao="Fonte: Comissão Europeia, Weekly Oil Bulletin",
        frequencia="semanal (terça/quinta)",
    ),
    "incidencias": dict(
        descricao="Incidências de trânsito activas na rede DGT (DATEX II v3.7)",
        url=DGT,
        licenca="Ficha NAP: CC BY, gratuita (Reg. UE 886/2013). ⚠ Confirmar por email ao NAP que prevalece sobre o aviso legal geral da DGT",
        uso_comercial=True,
        atribuicao="Fuente: DGT",
        frequencia="5 min",
    ),
    "festivos": dict(
        descricao="Feriados nacionais e regionais ES (BOE) e nacionais PT (Código do Trabalho)",
        url="https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-21667",
        licenca="BOE: licencia tipo (uso comercial gratuito); DRE: legislação pública. "
        "Nager.Date só como fallback opcional (--festivos-nager) e marcado nao-comercial",
        uso_comercial=True,
        atribuicao="Basado en datos de la Agencia Estatal Boletín Oficial del Estado (boe.es); Diário da República",
        frequencia="mensal (verificar resolução anual em Outubro)",
    ),
    "cambio": dict(
        descricao="Câmbios de referência BCE, últimos 90 dias",
        url="https://frankfurter.dev",
        licenca="BCE: reprodução com o BCE citado como fonte; Frankfurter «free for commercial use»",
        uso_comercial=True,
        atribuicao="Fuente: BCE (tipos de referencia, gratuitos en ecb.europa.eu). Se o dado entra num produto vendido, "
        "o comprador deve saber que é gratuito no site do BCE; o BCE desaconselha o uso para transacções",
        frequencia="diária (16:30 CET)",
    ),
    "tempo": dict(
        descricao="Previsão diária 7 dias nas cidades das rotas",
        url=OPENMETEO,
        licenca="Open-Meteo grátis: nao-comercial (Standard ~29€/mês para uso comercial); dados CC BY 4.0. "
        "AEMET OpenData (comercial OK) substitui as cidades ES quando há AEMET_API_KEY",
        uso_comercial=False,
        atribuicao="Weather data by Open-Meteo.com (CC BY 4.0) · Fuente: AEMET (quando aplicável)",
        frequencia="6 h",
    ),
    "portagens": dict(
        descricao="Portagens de referência 2026 (tabela manual, corredores da demo)",
        url="ver coluna fonte por linha",
        licenca="Tarifas públicas (BOE / concessionárias); compilação própria",
        uso_comercial=True,
        atribuicao="Fontes por linha (BOE, Brisa, administracion.gob.es)",
        frequencia="anual (Janeiro)",
    ),
    "restricoes": dict(
        descricao="Restrições DGT 2026 a >7.500 kg no corredor A-5 (Anexo II)",
        url=R.F_DGT_2026.split(": ", 1)[-1],
        licenca="BOE: licencia tipo",
        uso_comercial=True,
        atribuicao="Basado en datos de la DGT / Agencia Estatal Boletín Oficial del Estado",
        frequencia="anual + resoluções avulsas",
    ),
}
ORDEM = list(CATALOGO)


# ── HTTP ─────────────────────────────────────────────────────────────────────


def sessao():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update(UA)
    return s


def obter(s, url, timeout=60, **kw):
    r = s.get(url, timeout=timeout, **kw)
    r.raise_for_status()
    return r


# ── Base de dados ────────────────────────────────────────────────────────────


def _dsn_da_demo():
    """A base sintética da demonstração (`skydemo`), pelo mesmo acesso do seed
    dos sectores — dentro do pod, sem a credencial passar por mãos."""
    host, user, pwd = (
        os.environ.get(k, "") for k in ("DEMO_PG_HOST", "DEMO_PG_USER", "DEMO_PG_PASSWORD")
    )
    if not (host and user and pwd):
        raise SystemExit("--demo exige DEMO_PG_HOST / DEMO_PG_USER / DEMO_PG_PASSWORD")
    from urllib.parse import quote_plus

    porta = os.environ.get("DEMO_PG_PORT", "5432")
    base = os.environ.get("DEMO_PG_DB", "skydemo")
    return f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(pwd)}@{host}:{porta}/{base}?sslmode=require"


def motor(dsn=None, sqlite=None, esquema=None):
    if esquema and not sqlite:
        # Noutro esquema (p.ex. `ops`, o que a ligação «Operaciones» vê): uma
        # ligação Postgres só descobre UM esquema, e as perguntas que cruzam
        # os dados da empresa com os públicos precisam dos dois juntos.
        eng = _motor_pg(dsn)
        return eng.execution_options(schema_translate_map={E.ESQUEMA: esquema})
    if sqlite:
        eng = create_engine(f"sqlite:///{sqlite}", future=True)
        # Em SQLite não há esquemas: as tabelas ficam sem prefixo «mundo.».
        return eng.execution_options(schema_translate_map={E.ESQUEMA: None})
    return _motor_pg(dsn)


def _motor_pg(dsn):
    if not dsn:
        raise SystemExit("Indique --dsn, MUNDO_DSN, --demo ou --sqlite")
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        dsn = "postgresql+psycopg2://" + dsn.split("://", 1)[1]
    return create_engine(dsn, future=True)


def criar_esquema(eng):
    with eng.begin() as c:
        if c.dialect.name == "postgresql":
            destino = (c.get_execution_options().get("schema_translate_map") or {}).get(
                E.ESQUEMA, E.ESQUEMA
            )
            # Só se não existir: o utilizador da demo pode criar tabelas no
            # `ops` mas não esquemas na base, e o Postgres verifica o
            # privilégio mesmo com IF NOT EXISTS («permission denied for
            # database skydemo», primeira carga em produção, 10/10).
            existe = c.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": destino},
            ).first()
            if not existe:
                c.execute(text(f"CREATE SCHEMA {destino}"))
        E.meta.create_all(c)


def upsert(conn, tabela, linhas, lote=500):
    """INSERT … ON CONFLICT (chave primária) DO UPDATE. Postgres e SQLite."""
    if not linhas:
        return 0
    ins = pg_dialect.insert if conn.dialect.name == "postgresql" else sqlite_dialect.insert
    chave = [c.name for c in tabela.primary_key.columns]
    # remove duplicados de chave dentro do mesmo lote (o último ganha)
    unicas = {tuple(r[k] for k in chave): r for r in linhas}
    linhas = list(unicas.values())
    for i in range(0, len(linhas), lote):
        st = ins(tabela).values(linhas[i : i + lote])
        resto = {c.name: st.excluded[c.name] for c in tabela.columns if c.name not in chave}
        st = (
            st.on_conflict_do_update(index_elements=chave, set_=resto)
            if resto
            else st.on_conflict_do_nothing()
        )
        conn.execute(st)
    return len(linhas)


def agora():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


# ── Fontes ───────────────────────────────────────────────────────────────────


def f_rotas(s, eng, args):
    t0 = agora()
    linhas = []
    for o, d in T.ROTAS_DEMO:
        a, b = T.CIDADES[o], T.CIDADES[d]
        url = OSRM.format(lat1=a[0], lon1=a[1], lat2=b[0], lon2=b[1])
        j = obter(s, url, timeout=30, params=dict(overview="full", geometries="geojson")).json()
        linhas.append(T.t_osrm(j, o, d, agora()))
        time.sleep(1.0)  # política do servidor demo: ≤1 pedido/s
    with eng.begin() as c:
        n = upsert(c, E.rotas_referencia, linhas)
    return n, t0


def _rotas_guardadas(eng):
    with eng.connect() as c:
        return [dict(r._mapping) for r in c.execute(select(E.rotas_referencia))]


def f_gasolineras(s, eng, args):
    j = obter(s, MITECO + "/EstacionesTerrestres/", timeout=120).json()
    linhas, fecha = T.t_miteco_actual(j)
    if len(linhas) < 1000:
        raise RuntimeError(f"MITECO devolveu só {len(linhas)} postos — fotografia recusada")
    rotas = _rotas_guardadas(eng)
    perto = T.postos_perto_de_rotas(linhas, rotas, raio_km=5.0, calculado_em=agora())
    hoje = (fecha or agora()).astimezone(T.MADRID).date()
    agreg = T.agregar_gasoleo(
        [(e["provincia"], e["precio_gasoleo_a"]) for e in linhas],
        hoje,
        "actual",
        "MITECO /EstacionesTerrestres/ (fotografia)",
    )
    with eng.begin() as c:
        n = upsert(c, E.gasolineras_precio, linhas)
        # postos que deixaram de constar na fotografia saem da tabela
        c.execute(
            delete(E.gasolineras_precio).where(E.gasolineras_precio.c.actualizado_em != fecha)
        )
        c.execute(delete(E.gasolineras_rota))
        upsert(c, E.gasolineras_rota, perto)
        # o agregado do dia corrente não pisa um «historico» já gravado
        tem_hist = c.execute(
            select(E.gasoleo_historico_diario.c.provincia).where(
                E.gasoleo_historico_diario.c.data == hoje,
                E.gasoleo_historico_diario.c.origem == "historico",
            )
        ).first()
        if not tem_hist:
            upsert(c, E.gasoleo_historico_diario, agreg)
    log.info("gasolineras: %d postos, %d ligações posto-rota (%d rotas)", n, len(perto), len(rotas))
    return n, fecha


def f_gasoleo_historico(s, eng, args):
    hoje = agora().astimezone(T.MADRID).date()
    total, ultima, erros = 0, None, []
    for k in range(args.dias_historico, 0, -1):
        dia = hoje - dt.timedelta(days=k)
        url = f"{MITECO}/EstacionesTerrestresHist/FiltroProducto/{dia:%d-%m-%Y}/4"
        try:
            j = obter(s, url, timeout=120).json()
        except Exception as e:  # um dia em falta não estraga os outros
            erros.append(f"{dia}: {e}")
            continue
        linhas = T.t_miteco_hist(j, dia)
        with eng.begin() as c:
            total += upsert(c, E.gasoleo_historico_diario, linhas)
        ultima = dt.datetime.combine(dia, dt.time(0), T.MADRID).astimezone(dt.timezone.utc)
    if erros and not total:
        raise RuntimeError("; ".join(erros[:3]))
    if erros:
        log.warning("gasoleo_historico: %d dias falharam: %s", len(erros), erros[:3])
    return total, ultima


def f_gasoleo_ue(s, eng, args):
    dados = obter(s, WOB, timeout=120).content
    desde = agora().date() - dt.timedelta(weeks=args.semanas_ue)
    linhas = T.t_wob(dados, desde=desde)
    with eng.begin() as c:
        n = upsert(c, E.gasoleo_ue_semanal, linhas)
    ultima = max((l["data"] for l in linhas), default=None)
    return n, dt.datetime.combine(ultima, dt.time(0), dt.timezone.utc) if ultima else None


def f_incidencias(s, eng, args):
    xml = obter(s, DGT, timeout=60).content
    visto = agora()
    linhas, pub = T.t_datex(xml)
    for l in linhas:
        l["visto_em"] = visto
    t = E.incidencias_trafico
    with eng.begin() as c:
        n = upsert(c, t, linhas)
        c.execute(update(t).where(t.c.visto_em < visto).values(activa=False))
        c.execute(delete(t).where(t.c.visto_em < visto - dt.timedelta(days=30)))
    return n, pub


def f_festivos(s, eng, args):
    linhas = R.festivos_oficiais()
    oficiais = {l["chave"] for l in linhas}
    if args.festivos_nager:
        ano = agora().year
        for a in (ano, ano + 1):
            for p in ("ES", "PT"):
                lst = obter(s, NAGER.format(ano=a, pais=p), timeout=30).json()
                linhas += [x for x in T.t_nager(lst, p) if x["chave"] not in oficiais]
    with eng.begin() as c:
        if not args.festivos_nager:  # não deixar restos de uma corrida com fallback
            c.execute(delete(E.festivos).where(E.festivos.c.licenca == "nao-comercial"))
        n = upsert(c, E.festivos, linhas)
    return n, None


def f_cambio(s, eng, args):
    fim = agora().date()
    ini = fim - dt.timedelta(days=90)
    ultimo_erro = None
    for base in FRANKFURTER:
        try:
            j = obter(s, f"{base}/{ini.isoformat()}..{fim.isoformat()}", timeout=30).json()
            break
        except Exception as e:
            ultimo_erro = e
    else:
        raise RuntimeError(f"Frankfurter indisponível: {ultimo_erro}")
    linhas = T.t_frankfurter(j)
    with eng.begin() as c:
        n = upsert(c, E.cambio_eur, linhas)
    ultima = max((l["data"] for l in linhas), default=None)
    # fixing BCE ~16:00 CET
    dado = (
        dt.datetime.combine(ultima, dt.time(16), T.MADRID).astimezone(dt.timezone.utc)
        if ultima
        else None
    )
    return n, dado


def _aemet(s, chave, cidade, cod):
    passo1 = obter(s, AEMET.format(cod=cod), timeout=30, params={"api_key": chave}).json()
    if not passo1.get("datos"):
        raise RuntimeError(f"AEMET {cidade}: {passo1.get('descripcion') or passo1}")
    return obter(s, passo1["datos"], timeout=30).json()


def f_tempo(s, eng, args):
    cidades = list(T.CIDADES)
    params = dict(
        latitude=",".join(f"{T.CIDADES[c][0]:.4f}" for c in cidades),
        longitude=",".join(f"{T.CIDADES[c][1]:.4f}" for c in cidades),
        daily="temperature_2m_min,temperature_2m_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max,weather_code",
        timezone="Europe/Madrid",
        forecast_days=7,
        wind_speed_unit="kmh",
    )
    pedido = agora()
    resp = obter(s, OPENMETEO, timeout=30, params=params).json()
    linhas = T.t_openmeteo(resp, cidades, pedido)
    chave = os.environ.get("AEMET_API_KEY")
    if chave:  # produção: AEMET (comercial) substitui as cidades espanholas
        por_cidade = {}
        for cidade, cod in T.AEMET_MUNICIPIOS.items():
            try:
                por_cidade[cidade] = T.t_aemet_diaria(
                    _aemet(s, chave, cidade, cod), cidade, agora()
                )
            except Exception as e:
                log.warning("AEMET %s falhou (fica Open-Meteo): %s", cidade, e)
        linhas = [l for l in linhas if l["cidade"] not in por_cidade] + [
            x for v in por_cidade.values() for x in v
        ]
    with eng.begin() as c:
        n = upsert(c, E.tempo_cidades, linhas)
    return n, pedido  # o Open-Meteo não publica a hora da corrida do modelo


def f_portagens(s, eng, args):
    with eng.begin() as c:
        c.execute(delete(E.portagens))  # tabela manual: substitui por inteiro
        n = upsert(c, E.portagens, R.portagens())
    return n, dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)


def f_restricoes(s, eng, args):
    with eng.begin() as c:
        c.execute(delete(E.restricoes_pesados))
        n = upsert(c, E.restricoes_pesados, R.restricoes_pesados())
    return n, dt.datetime(2026, 1, 14, tzinfo=dt.timezone.utc)


FUNCOES = {
    "rotas": f_rotas,
    "gasolineras": f_gasolineras,
    "gasoleo_historico": f_gasoleo_historico,
    "gasoleo_ue": f_gasoleo_ue,
    "incidencias": f_incidencias,
    "festivos": f_festivos,
    "cambio": f_cambio,
    "tempo": f_tempo,
    "portagens": f_portagens,
    "restricoes": f_restricoes,
}


def registar(eng, nome, linhas, dado_de, erro, ms):
    meta = CATALOGO[nome]
    linha = dict(
        nome=nome,
        **meta,
        ultima_actualizacao=agora(),
        dado_de=dado_de,
        linhas=linhas,
        estado="erro" if erro else "ok",
        erro=erro,
        duracao_ms=ms,
    )
    with eng.begin() as c:
        if erro:  # numa falha, manter as linhas/dado_de da última corrida boa
            ant = c.execute(select(E.fontes).where(E.fontes.c.nome == nome)).first()
            if ant:
                linha["linhas"], linha["dado_de"] = ant.linhas, ant.dado_de
        upsert(c, E.fontes, [linha])


def correr(eng, so=None, args=None):
    s = sessao()
    resultados = []
    for nome in ORDEM:
        if so and nome not in so:
            continue
        t0 = time.perf_counter()
        erro, n, dado = None, 0, None
        try:
            n, dado = FUNCOES[nome](s, eng, args)
        except Exception as e:
            erro = f"{type(e).__name__}: {e}"[:1000]
            log.error("fonte %s falhou: %s", nome, erro)
            log.debug(traceback.format_exc())
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            registar(eng, nome, n, dado, erro, ms)
        except Exception as e:  # nem o registo pode parar as outras fontes
            log.error("não consegui registar %s em mundo.fontes: %s", nome, e)
        resultados.append((nome, n, dado, erro, ms))
    return resultados


def imprimir(resultados):
    print(f"\n{'fonte':18} {'estado':6} {'linhas':>7} {'ms':>7}  dado de (UTC)        erro")
    print("-" * 100)
    for nome, n, dado, erro, ms in resultados:
        d = dado.strftime("%Y-%m-%d %H:%M") if dado else "-"
        print(f"{nome:18} {'ERRO' if erro else 'ok':6} {n:7d} {ms:7d}  {d:20} {(erro or '')[:60]}")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Carrega dados públicos para o esquema «mundo».")
    ap.add_argument(
        "--dsn", default=os.environ.get("MUNDO_DSN"), help="DSN Postgres (ou env MUNDO_DSN)"
    )
    ap.add_argument("--sqlite", help="Ficheiro SQLite para testes locais (sem esquemas)")
    ap.add_argument("--so", action="append", choices=ORDEM, help="Só esta(s) fonte(s); repetível")
    ap.add_argument(
        "--dias-historico", type=int, default=7, help="Dias de histórico MITECO (omissão 7)"
    )
    ap.add_argument(
        "--semanas-ue", type=int, default=52, help="Semanas do Weekly Oil Bulletin (omissão 52)"
    )
    ap.add_argument(
        "--festivos-nager",
        action="store_true",
        help="Completar feriados com Nager.Date (licença NÃO-COMERCIAL; só para testes)",
    )
    ap.add_argument(
        "--demo", action="store_true", help="Base da demonstração (DEMO_PG_*), dentro do pod"
    )
    ap.add_argument(
        "--esquema", help="Esquema de destino (por omissão «mundo»; p.ex. «ops» para a demo)"
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.demo and not args.dsn:
        args.dsn = _dsn_da_demo()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    eng = motor(args.dsn, args.sqlite, args.esquema)
    criar_esquema(eng)
    res = correr(eng, set(args.so) if args.so else None, args)
    imprimir(res)
    return 1 if all(r[3] for r in res) else 0
