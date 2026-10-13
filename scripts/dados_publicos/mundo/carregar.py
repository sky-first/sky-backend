# -*- coding: utf-8 -*-
"""
Orquestração: descarrega cada fonte, transforma, faz upsert por chave natural
e regista o resultado em ``mundo.fontes``. Cada fonte corre isolada: se uma
falhar, as outras continuam e o erro fica em ``mundo.fontes.erro``.

Fontes pagas (tempo, rotas) só correm com chave em variável de ambiente
(``AEMET_API_KEY``, ``OPEN_METEO_API_KEY``, ``TOMTOM_API_KEY``). Sem chave
não chamam nada: ``fontes.estado = sem_chave`` e as linhas anteriores ficam,
cada uma com a sua licença. Os servidores grátis não-comerciais (Open-Meteo
grátis, OSRM demo) só com ``--permitir-nao-comercial``, recusado dentro do
Kubernetes.
"""

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
import time
import traceback

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import create_engine, delete, func, inspect, or_, select, text, update
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
FRANKFURTER = ["https://api.frankfurter.dev/v1", "https://api.frankfurter.app"]
# Open-Meteo: só o endpoint de cliente (subscrição) em produção. O grátis é
# «only for non-commercial purposes» e só corre com --permitir-nao-comercial.
OPENMETEO_CLIENTE = "https://customer-api.open-meteo.com/v1/forecast"
OPENMETEO_GRATIS = "https://api.open-meteo.com/v1/forecast"
AEMET = "https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio/diaria/{cod}"
TOMTOM = "https://api.tomtom.com/routing/1/calculateRoute/{lat1},{lon1}:{lat2},{lon2}/json"
# OSRM demo: «reasonable, non-commercial use». Só com --permitir-nao-comercial.
OSRM = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
WOB = (
    "https://energy.ec.europa.eu/document/download/906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
    "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx"
)

# nome → metadados para mundo.fontes (licença e atribuição: DADOS_EXTERNOS_COMERCIAL_2026-10.md)
CATALOGO = {
    "rotas": dict(
        descricao="Distância e tempo de camião origem–destino (rotas da demo) + pausas Reg. 561/2006",
        url="https://developer.tomtom.com/routing-api/documentation",
        licenca=T.LICENCA_TOMTOM + ". Só corre com TOMTOM_API_KEY",
        uso_comercial=True,
        atribuicao="Routing © TomTom",
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
        descricao="Feriados nacionais e regionais ES (resolução anual do BOE) e nacionais PT (Código do Trabalho, art. 234.º)",
        url="https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-21667",
        licenca=R.LIC_BOE + "; " + R.LIC_DRE,
        uso_comercial=True,
        atribuicao="Basado en datos de la Agencia Estatal Boletín Oficial del Estado (boe.es); Fonte: Diário da República",
        frequencia="mensal (verificar a resolução BOE de fiestas laborales, publicada em Outubro)",
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
        descricao="Previsão diária 7 dias nas cidades das rotas: AEMET (cidades ES) e Open-Meteo com subscrição",
        url="https://opendata.aemet.es · " + OPENMETEO_CLIENTE,
        licenca=T.LICENCA_AEMET
        + " · "
        + T.LICENCA_OPENMETEO_CLIENTE
        + ". Só corre com AEMET_API_KEY e/ou OPEN_METEO_API_KEY",
        uso_comercial=True,
        atribuicao="Fuente: AEMET · Weather data by Open-Meteo.com (CC BY 4.0)",
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

# Licença gravada em cada linha das tabelas que não a trazem da transformação.
LICENCA_POR_TABELA = {
    "gasolineras_precio": "MITECO — reutilização (Lei 37/2007, RD 1495/2011)",
    "gasoleo_historico_diario": "MITECO — reutilização (Lei 37/2007, RD 1495/2011)",
    "gasoleo_ue_semanal": "Comissão Europeia — reutilização com citação (Decisão 2011/833/UE)",
    "incidencias_trafico": "DGT NAP — CC BY (Reg. UE 886/2013)",
    "cambio_eur": "BCE — reprodução com citação; Frankfurter «free for commercial use»",
    "portagens": "Tarifas públicas (BOE / concessionárias); compilação própria",
    "restricoes_pesados": R.LIC_BOE,
}


class SemChave(Exception):
    """Fonte paga sem chave configurada: não corre, e as linhas anteriores ficam."""

    estado = "sem_chave"

    def __init__(self, msg, **meta):
        super().__init__(msg)
        self.meta = meta


class TermosPorConfirmar(SemChave):
    """A fonte não pode ser guardada na base partilhada até os termos estarem confirmados.

    Hoje: rotas TomTom em ``sky_world`` (os termos de cache/armazenamento da
    TomTom estão por confirmar — L2 do desenho das fontes do sistema). Não
    chama a API e não grava nada; não conta como erro.
    """

    estado = "termos_por_confirmar"


def _chave(nome):
    return (os.environ.get(nome) or "").strip()


_RE_SEGREDO = re.compile(r"((?:api_?key|key|token)=)[^&\s'\"]+", re.I)


def sem_segredos(texto):
    """Tira chaves de API de mensagens (os erros do requests trazem o URL)."""
    return _RE_SEGREDO.sub(r"\1***", texto or "")


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
        _colunas_novas(c)


def _colunas_novas(c):
    """ALTER TABLE ADD COLUMN para colunas do esquema que a tabela ainda não tem.

    O create_all não altera tabelas existentes; as colunas acrescentadas
    depois da primeira carga (licenca, fonte…) chegam por aqui. Só acrescenta,
    nunca apaga nem muda tipos.
    """
    destino = (c.get_execution_options().get("schema_translate_map") or {}).get(
        E.ESQUEMA, E.ESQUEMA
    )
    insp = inspect(c)
    for t in E.meta.sorted_tables:
        existentes = {col["name"] for col in insp.get_columns(t.name, schema=destino)}
        prefixo = f"{destino}." if destino else ""
        for col in t.columns:
            if col.name in existentes:
                continue
            tipo = col.type.compile(dialect=c.dialect)
            c.execute(text(f'ALTER TABLE {prefixo}{t.name} ADD COLUMN "{col.name}" {tipo}'))
            if col.comment and c.dialect.name == "postgresql":
                c.execute(
                    text(f'COMMENT ON COLUMN {prefixo}{t.name}."{col.name}" IS :c'),
                    {"c": col.comment},
                )
            log.info("coluna nova %s%s.%s", prefixo, t.name, col.name)


def upsert(conn, tabela, linhas, lote=500):
    """INSERT … ON CONFLICT (chave primária) DO UPDATE. Postgres e SQLite."""
    if not linhas:
        return 0
    ins = pg_dialect.insert if conn.dialect.name == "postgresql" else sqlite_dialect.insert
    chave = [c.name for c in tabela.primary_key.columns]
    lic = LICENCA_POR_TABELA.get(tabela.name)
    if lic and "licenca" in tabela.c:
        linhas = [r if r.get("licenca") else dict(r, licenca=lic) for r in linhas]
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


def _comercial_na_tabela(eng, tabela):
    """True/False se as linhas que lá estão são todas de licença comercial; None se vazia."""
    with eng.connect() as c:
        lics = c.execute(select(tabela.c.licenca).distinct()).scalars().all()
    if not lics:
        return None
    return all(T.licenca_comercial(x) for x in lics)


def _osrm(s, a, b):
    url = OSRM.format(lat1=a[0], lon1=a[1], lat2=b[0], lon2=b[1])
    j = obter(s, url, timeout=30, params=dict(overview="full", geometries="geojson")).json()
    time.sleep(1.0)  # política do servidor demo: ≤1 pedido/s
    return j


def f_rotas(s, eng, args):
    if getattr(args, "mundo_partilhado", False) and not getattr(
        args, "guardar_rotas_tomtom", False
    ):
        # Antes de qualquer pedido: na base que os clientes leem não se
        # guardam resultados da TomTom até os termos estarem confirmados.
        raise TermosPorConfirmar(
            "rotas: termos de armazenamento da TomTom por confirmar — nada pedido, "
            "nada gravado na base partilhada (usar --guardar-rotas-tomtom quando "
            "estiverem confirmados por escrito)",
            uso_comercial=None,
        )
    chave = _chave("TOMTOM_API_KEY")
    t0 = agora()
    linhas = []
    if chave:
        for o, d in T.ROTAS_DEMO:
            a, b = T.CIDADES[o], T.CIDADES[d]
            url = TOMTOM.format(lat1=a[0], lon1=a[1], lat2=b[0], lon2=b[1])
            j = obter(s, url, timeout=30, params=dict(T.CAMIAO_TOMTOM, key=chave)).json()
            linhas.append(T.t_tomtom(j, o, d, agora()))
            time.sleep(0.25)  # TomTom: ≤5 pedidos/s
        meta = {}
    elif getattr(args, "permitir_nao_comercial", False):
        log.warning("rotas: OSRM demo (NÃO-COMERCIAL) por --permitir-nao-comercial")
        for o, d in T.ROTAS_DEMO:
            linhas.append(T.t_osrm(_osrm(s, T.CIDADES[o], T.CIDADES[d]), o, d, agora()))
        meta = dict(
            url="https://router.project-osrm.org",
            licenca="demo-nao-comercial: OSRM demo «reasonable, non-commercial use»; dados OSM ODbL. "
            "Carregado com --permitir-nao-comercial (só testes locais)",
            atribuicao="© OpenStreetMap contributors (ODbL)",
            uso_comercial=False,
        )
    else:
        raise SemChave(
            "sem TOMTOM_API_KEY: rotas não actualizadas (o OSRM público é não-comercial); "
            "ficam as linhas anteriores com a sua licença",
            uso_comercial=_comercial_na_tabela(eng, E.rotas_referencia),
        )
    with eng.begin() as c:
        n = upsert(c, E.rotas_referencia, linhas)
    return n, t0, meta


def _rotas_guardadas(eng):
    with eng.connect() as c:
        return [dict(r._mapping) for r in c.execute(select(E.rotas_referencia))]


#: Uma fotografia do MITECO com menos de 80 % dos postos da anterior é parcial.
LIMIAR_FOTOGRAFIA = 0.8


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
    with eng.connect() as c:
        anteriores = c.execute(select(func.count()).select_from(E.gasolineras_precio)).scalar()
    novos = len({e["id_estacion"] for e in linhas})
    if anteriores and novos < LIMIAR_FOTOGRAFIA * anteriores:
        # Uma fotografia parcial do MITECO apagava os postos que faltam. Fica
        # o dado anterior com o dado_de antigo (a resposta diz «atrasado»).
        raise RuntimeError(
            f"MITECO devolveu {novos} postos contra {anteriores} na carga anterior "
            f"(< {int(LIMIAR_FOTOGRAFIA * 100)} %) — fotografia parcial recusada, nada apagado"
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
    # Os preços são MITECO (comercial); a ligação posto-rota herda a licença
    # do traçado, que pode ainda ser OSRM (não-comercial).
    tracado_ok = all(T.licenca_comercial(r.get("licenca")) for r in rotas)
    return n, fecha, ({} if tracado_ok else dict(uso_comercial=False))


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
    ano = agora().year
    linhas = R.festivos_oficiais(range(min(2026, ano), ano + 2))
    with eng.begin() as c:
        # Restos de cargas antigas com o Nager.Date (não-comercial) saem sempre.
        c.execute(
            delete(E.festivos).where(
                or_(E.festivos.c.licenca.like("%nao-comercial%"), E.festivos.c.fonte.like("Nager%"))
            )
        )
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


def _json_aemet(r):
    """Os «datos» da AEMET vêm em ISO-8859-15; aceitar também UTF-8."""
    try:
        txt = r.content.decode("utf-8")
    except UnicodeDecodeError:
        txt = r.content.decode("iso-8859-15")
    return json.loads(txt)


def _aemet(s, chave, cidade, cod):
    # Chave no cabeçalho (a AEMET aceita-o), para não ir parar a URLs nos logs.
    passo1 = obter(s, AEMET.format(cod=cod), timeout=30, headers={"api_key": chave}).json()
    if not passo1.get("datos"):
        raise RuntimeError(f"AEMET {cidade}: {passo1.get('descripcion') or passo1}")
    return _json_aemet(obter(s, passo1["datos"], timeout=30))


def _openmeteo(s, cidades, chave):
    params = dict(
        latitude=",".join(f"{T.CIDADES[c][0]:.4f}" for c in cidades),
        longitude=",".join(f"{T.CIDADES[c][1]:.4f}" for c in cidades),
        daily="temperature_2m_min,temperature_2m_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max,weather_code",
        timezone="Europe/Madrid",
        forecast_days=7,
        wind_speed_unit="kmh",
    )
    if chave:
        params["apikey"] = chave
        return obter(s, OPENMETEO_CLIENTE, timeout=30, params=params).json()
    return obter(s, OPENMETEO_GRATIS, timeout=30, params=params).json()


def f_tempo(s, eng, args):
    aemet, om = _chave("AEMET_API_KEY"), _chave("OPEN_METEO_API_KEY")
    gratis = getattr(args, "permitir_nao_comercial", False) and not om
    if not (aemet or om or gratis):
        raise SemChave(
            "sem AEMET_API_KEY nem OPEN_METEO_API_KEY: tempo não actualizado "
            "(o Open-Meteo grátis é só não-comercial); ficam as linhas anteriores com a sua licença",
            uso_comercial=_comercial_na_tabela(eng, E.tempo_cidades),
        )
    pedido = agora()
    por_cidade = {}
    if aemet:  # AEMET (oficial, comercial) nas cidades espanholas
        for cidade, cod in T.AEMET_MUNICIPIOS.items():
            try:
                por_cidade[cidade] = T.t_aemet_diaria(_aemet(s, aemet, cidade, cod), cidade, pedido)
            except Exception as e:
                log.warning("AEMET %s falhou: %s", cidade, sem_segredos(str(e)))
    faltam = [c for c in T.CIDADES if c not in por_cidade]
    if faltam and (om or gratis):
        if gratis:
            log.warning("tempo: Open-Meteo GRÁTIS (NÃO-COMERCIAL) por --permitir-nao-comercial")
        lic = T.LICENCA_OPENMETEO_CLIENTE if om else T.LICENCA_OPENMETEO
        fonte = "Open-Meteo customer-api /v1/forecast" if om else "Open-Meteo /v1/forecast (grátis)"
        resp = _openmeteo(s, faltam, om)
        for l in T.t_openmeteo(resp, faltam, pedido, fonte=fonte, licenca=lic):
            por_cidade.setdefault(l["cidade"], []).append(l)
    elif faltam:
        log.info("tempo: sem OPEN_METEO_API_KEY, ficam por actualizar: %s", ", ".join(faltam))
    linhas = [l for v in por_cidade.values() for l in v]
    if not linhas:
        raise RuntimeError("nenhuma cidade com previsão (ver avisos AEMET)")
    with eng.begin() as c:
        n = upsert(c, E.tempo_cidades, linhas)
    dado = max((l["actualizado_em"] for l in linhas if l["actualizado_em"]), default=pedido)
    meta = {}
    if gratis:
        meta = dict(
            url=OPENMETEO_GRATIS,
            licenca=T.LICENCA_OPENMETEO
            + ". Carregado com --permitir-nao-comercial (só testes locais)",
        )
    meta["uso_comercial"] = _comercial_na_tabela(eng, E.tempo_cidades)
    return n, dado, meta


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


def registar(eng, nome, linhas, dado_de, erro, ms, estado=None, meta=None):
    estado = estado or ("erro" if erro else "ok")
    linha = dict(
        nome=nome,
        **dict(CATALOGO[nome], **(meta or {})),
        ultima_actualizacao=agora(),
        dado_de=dado_de,
        linhas=linhas,
        estado=estado,
        erro=erro,
        duracao_ms=ms,
    )
    with eng.begin() as c:
        if estado != "ok":  # falha ou sem chave: manter linhas/dado_de da última corrida boa
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
        erro, n, dado, estado, meta = None, 0, None, "ok", None
        try:
            r = FUNCOES[nome](s, eng, args)
            n, dado = r[0], r[1]
            meta = r[2] if len(r) > 2 else None
        except SemChave as e:
            estado, erro, meta = e.estado, str(e), e.meta
            log.warning("fonte %s sem chave: %s", nome, erro)
        except Exception as e:
            estado = "erro"
            erro = sem_segredos(f"{type(e).__name__}: {e}")[:1000]
            log.error("fonte %s falhou: %s", nome, erro)
            log.debug(sem_segredos(traceback.format_exc()))
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            registar(eng, nome, n, dado, erro, ms, estado, meta)
        except Exception as e:  # nem o registo pode parar as outras fontes
            log.error("não consegui registar %s em mundo.fontes: %s", nome, e)
        resultados.append((nome, n, dado, erro, ms, estado))
    return resultados


# ── Base partilhada (sky_world) ──────────────────────────────────────────────

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def preparar_mundo_partilhado(eng, args):
    """O que muda quando o destino é a base ``sky_world`` que os clientes leem.

    1. Linhas com licença não-comercial não ficam lá (p.ex. OSRM antigo).
    2. Sem ``--guardar-rotas-tomtom``, a ``rotas_referencia`` fica vazia: os
       termos de armazenamento da TomTom estão por confirmar. A
       ``gasolineras_rota`` herda esse traçado e fica vazia também.
    3. O ``world_admin`` recebe SELECT com GRANT OPTION nas tabelas (o
       bootstrap já o deixa por omissão para as novas; isto cobre as antigas).
    """
    apagadas = {}
    with eng.begin() as c:
        for t in E.meta.sorted_tables:
            if t.name == "fontes" or "licenca" not in t.c:
                continue
            r = c.execute(delete(t).where(t.c.licenca.like("%nao-comercial%")))
            if r.rowcount:
                apagadas[t.name] = r.rowcount
        if not getattr(args, "guardar_rotas_tomtom", False):
            for t in (E.gasolineras_rota, E.rotas_referencia):
                r = c.execute(delete(t))
                if r.rowcount:
                    apagadas[t.name] = apagadas.get(t.name, 0) + r.rowcount
    if apagadas:
        log.warning("base partilhada: linhas retiradas %s", apagadas)
    papel = os.environ.get("WORLD_ADMIN_ROLE", "world_admin")
    if eng.dialect.name == "postgresql" and _IDENT.match(papel):
        with eng.begin() as c:
            if c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": papel}).first():
                c.execute(
                    text(
                        f'GRANT SELECT ON ALL TABLES IN SCHEMA {E.ESQUEMA} TO "{papel}" '
                        "WITH GRANT OPTION"
                    )
                )
    return apagadas


def imprimir(resultados):
    print(f"\n{'fonte':18} {'estado':7} {'linhas':>7} {'ms':>7}  dado de (UTC)        erro")
    print("-" * 100)
    for nome, n, dado, erro, ms, estado in resultados:
        d = dado.strftime("%Y-%m-%d %H:%M") if dado else "-"
        rot = {"erro": "ERRO", "sem_chave": "S/CHAVE"}.get(estado, estado)
        print(f"{nome:18} {rot:7} {n:7d} {ms:7d}  {d:20} {(erro or '')[:60]}")


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
        "--permitir-nao-comercial",
        action="store_true",
        help="Sem chaves, usar o Open-Meteo grátis e o OSRM demo (licenças NÃO-COMERCIAIS; "
        "só experiências locais, recusado dentro do Kubernetes)",
    )
    ap.add_argument(
        "--demo", action="store_true", help="Base da demonstração (DEMO_PG_*), dentro do pod"
    )
    ap.add_argument(
        "--esquema", help="Esquema de destino (por omissão «mundo»; p.ex. «ops» para a demo)"
    )
    ap.add_argument(
        "--mundo-partilhado",
        action="store_true",
        default=os.environ.get("MUNDO_PARTILHADO", "").lower() in ("1", "true", "sim"),
        help="O destino é a base sky_world que os clientes leem (fontes do sistema): "
        "esquema «mundo», só licenças comerciais, sem rotas TomTom guardadas",
    )
    ap.add_argument(
        "--guardar-rotas-tomtom",
        action="store_true",
        help="Com --mundo-partilhado, guardar rotas TomTom (só depois de os termos de "
        "armazenamento estarem confirmados por escrito)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.permitir_nao_comercial and os.environ.get("KUBERNETES_SERVICE_HOST"):
        ap.error("--permitir-nao-comercial não é permitido em produção (Kubernetes)")
    if args.mundo_partilhado:
        if args.permitir_nao_comercial:
            ap.error("--mundo-partilhado não aceita --permitir-nao-comercial")
        if args.esquema not in (None, E.ESQUEMA):
            ap.error(f"--mundo-partilhado escreve só no esquema «{E.ESQUEMA}»")
        if args.demo:
            ap.error("--mundo-partilhado não se mistura com --demo (a base é a sky_world)")
    if args.demo and not args.dsn:
        args.dsn = _dsn_da_demo()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    eng = motor(args.dsn, args.sqlite, args.esquema)
    criar_esquema(eng)
    if args.mundo_partilhado:
        preparar_mundo_partilhado(eng, args)
    res = correr(eng, set(args.so) if args.so else None, args)
    imprimir(res)
    return 1 if res and all(r[5] == "erro" for r in res) else 0
