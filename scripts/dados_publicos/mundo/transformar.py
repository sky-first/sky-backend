# -*- coding: utf-8 -*-
"""
Transformações puras: resposta da fonte (JSON / XML / XLSX em bytes) → linhas
planas (``list[dict]``) prontas para o upsert. Sem rede e sem base de dados,
para se poderem testar com ficheiros gravados (``fixtures/``).
"""

import datetime as dt
import io
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
UTC = dt.timezone.utc
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# Cidades da sementeira «Logística y Transporte» (ops.routes). Nomes EXACTOS.
CIDADES = {
    "Lisboa": (38.7223, -9.1393, "PT"),
    "Porto": (41.1579, -8.6291, "PT"),
    "Coimbra": (40.2033, -8.4103, "PT"),
    "Braga": (41.5454, -8.4265, "PT"),
    "Viseu": (40.6566, -7.9125, "PT"),
    "Badajoz": (38.8794, -6.9707, "ES"),
    "Mérida": (38.9161, -6.3437, "ES"),
    "Almendralejo": (38.6833, -6.4075, "ES"),
    "Sevilla": (37.3891, -5.9845, "ES"),
    "Madrid": (40.4168, -3.7038, "ES"),
}

# Os 20 pares origem→destino de ops.routes (scripts/demo/seed_transport.sql).
ROTAS_DEMO = [
    ("Lisboa", "Badajoz"),
    ("Lisboa", "Porto"),
    ("Badajoz", "Mérida"),
    ("Lisboa", "Madrid"),
    ("Porto", "Braga"),
    ("Badajoz", "Sevilla"),
    ("Mérida", "Almendralejo"),
    ("Lisboa", "Sevilla"),
    ("Porto", "Coimbra"),
    ("Almendralejo", "Sevilla"),
    ("Porto", "Madrid"),
    ("Coimbra", "Lisboa"),
    ("Badajoz", "Almendralejo"),
    ("Mérida", "Sevilla"),
    ("Porto", "Viseu"),
    ("Badajoz", "Madrid"),
    ("Braga", "Coimbra"),
    ("Lisboa", "Mérida"),
    ("Porto", "Badajoz"),
    ("Coimbra", "Badajoz"),
]

WMO_PT = {
    0: "céu limpo",
    1: "pouco nublado",
    2: "parcialmente nublado",
    3: "encoberto",
    45: "nevoeiro",
    48: "nevoeiro com geada",
    51: "chuvisco fraco",
    53: "chuvisco",
    55: "chuvisco forte",
    56: "chuvisco gelado",
    57: "chuvisco gelado forte",
    61: "chuva fraca",
    63: "chuva",
    65: "chuva forte",
    66: "chuva gelada",
    67: "chuva gelada forte",
    71: "neve fraca",
    73: "neve",
    75: "neve forte",
    77: "grãos de neve",
    80: "aguaceiros fracos",
    81: "aguaceiros",
    82: "aguaceiros fortes",
    85: "aguaceiros de neve",
    86: "aguaceiros de neve fortes",
    95: "trovoada",
    96: "trovoada com granizo",
    99: "trovoada com granizo forte",
}


# ── utilitários ──────────────────────────────────────────────────────────────


def num_es(s):
    """'1,749' → 1.749 ; '' / None → None."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def iso_utc(s):
    """ISO 8601 com fuso → datetime UTC; None se vazio/inválido."""
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def fecha_miteco(s):
    """'10/10/2026 22:17:04' (hora de Madrid) → datetime UTC."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=MADRID).astimezone(UTC)
        except ValueError:
            continue
    return None


def haversine_km(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    d = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(d))


def _f(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ── MITECO ───────────────────────────────────────────────────────────────────

_RE_ESTRADA = re.compile(
    r"\b(AP|A|N|E|R|M|CM|EX|BA|CC|TO|SE|H|CO|CR|MU|C|CV|CL|LE|SA|AV|GR|J|MA)[- ]?(\d{1,3}[A-Z]?)\b"
)
_RE_PK = re.compile(r"\b(?:KM|KM\.|P\.?K\.?|PK)\s*([0-9]+(?:[.,][0-9]+)?)", re.I)
_RE_NACIONAL_ROMANA = re.compile(r"\bN-(VI|IV|V|III|II|I)\b")
_RE_PK_VIRG = re.compile(r",\s*([0-9]{1,3}(?:[.,][0-9]{1,3})?)\s*$")


def extrair_carretera(direccion):
    """Heurística sobre a morada do MITECO: ('A-5', 340.0) / (None, None).

    Só aceita a estrada se a morada indica via interurbana (CR, CARRETERA,
    AUTOVIA, AUTOPISTA, KM, ou o padrão 'A-5' explícito com hífen).
    """
    if not direccion:
        return None, None
    d = direccion.upper()
    interurbana = bool(re.search(r"\b(CR|CTRA|CARRETERA|AUTOVIA|AUTOVÍA|AUTOPISTA|KM|P\.?K)\b", d))
    romana = _RE_NACIONAL_ROMANA.search(d)  # N-V = antiga designação da A-5
    m = _RE_ESTRADA.search(d)
    if romana:
        estrada = f"N-{romana.group(1)}"
    elif m:
        explicita = "-" in d[m.start() : m.end()]
        if not (interurbana or explicita):
            return None, None
        estrada = f"{m.group(1)}-{m.group(2)}"
    else:
        return None, None
    pk = None
    mp = _RE_PK.search(d)
    if mp:
        pk = num_es(mp.group(1))
    else:
        mv = _RE_PK_VIRG.search(d)
        if mv and interurbana:
            pk = num_es(mv.group(1))
    return estrada, pk


def t_miteco_actual(j, fonte="MITECO PreciosCarburantes /EstacionesTerrestres/"):
    """JSON de /EstacionesTerrestres/ → (linhas gasolineras_precio, fecha_utc)."""
    fecha = fecha_miteco(j.get("Fecha"))
    out = []
    for e in j.get("ListaEESSPrecio") or []:
        try:
            ide = int(e.get("IDEESS"))
        except (TypeError, ValueError):
            continue
        lat, lon = num_es(e.get("Latitud")), num_es(e.get("Longitud (WGS84)"))
        estrada, pk = extrair_carretera(e.get("Dirección"))
        out.append(
            dict(
                id_estacion=ide,
                rotulo=(e.get("Rótulo") or "").strip() or None,
                direccion=(e.get("Dirección") or "").strip() or None,
                cp=(e.get("C.P.") or "").strip() or None,
                localidad=(e.get("Localidad") or "").strip() or None,
                municipio=(e.get("Municipio") or "").strip() or None,
                provincia=(e.get("Provincia") or "").strip() or None,
                cod_provincia=(e.get("IDProvincia") or "").strip() or None,
                lat=lat,
                lon=lon,
                carretera=estrada,
                pk=pk,
                margen=(e.get("Margen") or "").strip() or None,
                horario=(e.get("Horario") or "").strip() or None,
                tipo_venta=(e.get("Tipo Venta") or "").strip() or None,
                precio_gasoleo_a=num_es(e.get("Precio Gasoleo A")),
                precio_gasoleo_premium=num_es(e.get("Precio Gasoleo Premium")),
                precio_gasoleo_b=num_es(e.get("Precio Gasoleo B")),
                precio_gasolina_95=num_es(e.get("Precio Gasolina 95 E5")),
                precio_adblue=num_es(e.get("Precio Adblue")),
                actualizado_em=fecha,
                fonte=fonte,
            )
        )
    return out, fecha


def agregar_gasoleo(pares, data, origem, fonte):
    """pares = [(provincia, preco)] → linhas gasoleo_historico_diario (+ total ESPAÑA)."""
    por = defaultdict(list)
    for prov, p in pares:
        if p is None or p <= 0 or not prov:
            continue
        por[prov.strip().upper()].append(p)
        por["ESPAÑA"].append(p)
    out = []
    for prov, ps in sorted(por.items()):
        out.append(
            dict(
                data=data,
                provincia=prov,
                n_postos=len(ps),
                minimo=round(min(ps), 3),
                media=round(statistics.fmean(ps), 3),
                mediana=round(statistics.median(ps), 3),
                maximo=round(max(ps), 3),
                origem=origem,
                fonte=fonte,
            )
        )
    return out


def t_miteco_hist(j, data, fonte="MITECO /EstacionesTerrestresHist/FiltroProducto/{data}/4"):
    """JSON histórico de 1 produto (PrecioProducto) → agregados por província."""
    pares = [
        (e.get("Provincia"), num_es(e.get("PrecioProducto")))
        for e in (j.get("ListaEESSPrecio") or [])
    ]
    return agregar_gasoleo(pares, data, "historico", fonte)


# ── DGT DATEX II v3.x ────────────────────────────────────────────────────────

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def _loc(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _txt(el, nome):
    """Texto do primeiro descendente com nome local `nome` (ou None)."""
    if el is None:
        return None
    for e in el.iter():
        if _loc(e.tag) == nome and e.text and e.text.strip():
            return e.text.strip()
    return None


def _filho(el, nome):
    for e in el.iter():
        if _loc(e.tag) == nome:
            return e
    return None


def _subtipo(rec):
    for e in rec.iter():
        n = _loc(e.tag)
        if n in ("causeType", "detailedCauseType"):
            continue
        if (
            (
                n.endswith("ManagementType")
                or n.endswith("ObstructionType")
                or n.endswith("ConditionType")
                or n.endswith("TrafficType")
                or n == "genericSituationRecordName"
            )
            and e.text
            and e.text.strip()
        ):
            return e.text.strip()
    return None


def _registo(rec, sit_id, sit_gravidade, publicacao, fonte):
    causa_el = _filho(rec, "cause")
    detalhe = None
    dc = _filho(causa_el, "detailedCauseType") if causa_el is not None else None
    if dc is not None:
        for e in dc.iter():
            if e is not dc and e.text and e.text.strip():
                detalhe = e.text.strip()
                break
    ponto = _filho(rec, "from")
    if ponto is None:
        ponto = _filho(rec, "point")
    if ponto is None:
        ponto = _filho(rec, "locationReference")
    destino = _filho(rec, "to")
    return dict(
        id=rec.get("id"),
        versao=int(rec.get("version")) if (rec.get("version") or "").isdigit() else None,
        id_situacao=sit_id,
        tipo=(rec.get(XSI_TYPE) or "").split(":")[-1] or None,
        subtipo=_subtipo(rec),
        causa=_txt(causa_el, "causeType"),
        causa_detalhe=detalhe,
        carretera=_txt(rec, "roadName"),
        pk=_f(_txt(ponto, "kilometerPoint")),
        pk_fim=_f(_txt(destino, "kilometerPoint")) if destino is not None else None,
        sentido=_txt(rec, "tpegDirectionRoad") or _txt(rec, "tpegDirection"),
        municipio=_txt(ponto, "municipality"),
        provincia=_txt(ponto, "province"),
        comunidade=_txt(ponto, "autonomousCommunity"),
        lat=_f(_txt(ponto, "latitude")),
        lon=_f(_txt(ponto, "longitude")),
        inicio=iso_utc(_txt(rec, "overallStartTime")),
        fim=iso_utc(_txt(rec, "overallEndTime")),
        gravidade=_txt(rec, "severity") or sit_gravidade,
        estado=_txt(rec, "validityStatus"),
        activa=True,
        actualizado_em=publicacao,
        fonte=fonte,
    )


def t_datex(xml_bytes, fonte="DGT NAP DATEX II v3.7"):
    """XML DATEX II (SituationPublication) → (linhas, publicationTime UTC).

    iterparse por <situation>: memória constante e robusto a prefixos de
    namespace diferentes (só se olha para o nome local das tags).
    """
    publicacao = None
    out = []
    for _ev, el in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        n = _loc(el.tag)
        if n == "publicationTime" and publicacao is None:
            publicacao = iso_utc(el.text)
        elif n == "situation":
            sit_grav = None
            for c in el:
                if _loc(c.tag) == "overallSeverity" and c.text:
                    sit_grav = c.text.strip()
            for rec in el:
                if _loc(rec.tag) == "situationRecord" and rec.get("id"):
                    out.append(_registo(rec, el.get("id"), sit_grav, None, fonte))
            el.clear()
    for r in out:
        r["actualizado_em"] = publicacao
    return out, publicacao


# ── Nager.Date ───────────────────────────────────────────────────────────────


def t_nager(lista, pais, fonte="Nager.Date v3 (fallback)"):
    """Fallback opcional: a API grátis do Nager.Date é só não-comercial."""
    out = []
    for h in lista or []:
        try:
            d = dt.date.fromisoformat(h["date"])
        except (KeyError, ValueError):
            continue
        regioes = h.get("counties") or [None]
        if h.get("global"):
            regioes = [None]
        for reg in regioes:
            nota = None
            if pais == "ES" and d.weekday() == 6:
                nota = "Cai a domingo: as CCAA podem trasladar para segunda — confirmar no BOE"
            out.append(
                dict(
                    chave=f"{pais}|{reg or 'NAC'}|{d.isoformat()}",
                    data=d,
                    pais=pais,
                    regiao=reg,
                    nome=h.get("localName"),
                    nome_en=h.get("name"),
                    dia_semana=DIAS[d.weekday()],
                    nota=nota,
                    fonte=fonte,
                    licenca="nao-comercial",
                )
            )
    return out


# ── Frankfurter (BCE) ────────────────────────────────────────────────────────


def t_frankfurter(j, fonte="BCE via Frankfurter"):
    """Resposta de /v1/{ini}..{fim} → linhas (data, moeda, taxa)."""
    out = []
    rates = j.get("rates") or {}
    if rates and all(isinstance(v, (int, float)) for v in rates.values()):
        rates = {j.get("date"): rates}  # formato /latest
    for dia, moedas in rates.items():
        d = dt.date.fromisoformat(dia)
        for m, t in (moedas or {}).items():
            out.append(dict(data=d, moeda=m, taxa=float(t), fonte=fonte))
    return out


# ── Open-Meteo ───────────────────────────────────────────────────────────────

LICENCA_OPENMETEO = "nao-comercial (Open-Meteo Standard ~29€/mês para uso comercial)"
LICENCA_AEMET = "comercial-ok com atribuição (Lei 37/2007): «Fuente: AEMET»"


def t_openmeteo(resp, cidades, actualizado_em, fonte="Open-Meteo /v1/forecast"):
    """Resposta multi-local (lista, mesma ordem que `cidades`) → linhas por cidade×dia."""
    if isinstance(resp, dict):
        resp = [resp]
    out = []
    for nome, r in zip(cidades, resp):
        lat, lon, pais = CIDADES.get(nome, (r.get("latitude"), r.get("longitude"), None))
        d = r.get("daily") or {}
        for i, dia in enumerate(d.get("time") or []):

            def v(k):
                arr = d.get(k) or []
                return arr[i] if i < len(arr) else None

            cod = v("weather_code")
            out.append(
                dict(
                    cidade=nome,
                    data=dt.date.fromisoformat(dia),
                    pais=pais,
                    lat=lat,
                    lon=lon,
                    temp_min=v("temperature_2m_min"),
                    temp_max=v("temperature_2m_max"),
                    precipitacao_mm=v("precipitation_sum"),
                    vento_max_kmh=v("wind_speed_10m_max"),
                    rajada_max_kmh=v("wind_gusts_10m_max"),
                    codigo=int(cod) if cod is not None else None,
                    descricao=WMO_PT.get(int(cod)) if cod is not None else None,
                    actualizado_em=actualizado_em,
                    licenca=LICENCA_OPENMETEO,
                    fonte=fonte,
                )
            )
    return out


# ── AEMET OpenData (produção; precisa de AEMET_API_KEY) ─────────────────────

# Código INE do município (só cidades espanholas da demo).
AEMET_MUNICIPIOS = {
    "Badajoz": "06015",
    "Mérida": "06083",
    "Almendralejo": "06011",
    "Sevilla": "41091",
    "Madrid": "28079",
}


def _max_valor(lista, chave="value"):
    vals = []
    for x in lista or []:
        v = x.get(chave) if isinstance(x, dict) else None
        try:
            if v not in (None, ""):
                vals.append(float(v))
        except (TypeError, ValueError):
            pass
    return max(vals) if vals else None


def t_aemet_diaria(
    resp, cidade, actualizado_em, fonte="AEMET OpenData, predicción municipal diaria"
):
    """Resposta do 2.º passo (/prediccion/especifica/municipio/diaria) → linhas tempo_cidades.

    A previsão municipal diária da AEMET não dá precipitação em mm (só
    probabilidade): precipitacao_mm fica NULL. Vento = máximo das velocidades
    por período; rajada = máximo de rachaMax.
    """
    if isinstance(resp, list):
        resp = resp[0] if resp else {}
    lat, lon, pais = CIDADES[cidade]
    out = []
    for dia in (resp.get("prediccion") or {}).get("dia") or []:
        try:
            d = dt.date.fromisoformat((dia.get("fecha") or "")[:10])
        except ValueError:
            continue
        temp = dia.get("temperatura") or {}
        ceu = next(
            (c.get("descripcion") for c in dia.get("estadoCielo") or [] if c.get("descripcion")),
            None,
        )
        out.append(
            dict(
                cidade=cidade,
                data=d,
                pais=pais,
                lat=lat,
                lon=lon,
                temp_min=_f(temp.get("minima")),
                temp_max=_f(temp.get("maxima")),
                precipitacao_mm=None,
                vento_max_kmh=_max_valor(dia.get("viento"), "velocidad"),
                rajada_max_kmh=_max_valor(dia.get("rachaMax")),
                codigo=None,
                descricao=ceu,
                actualizado_em=actualizado_em,
                licenca=LICENCA_AEMET,
                fonte=fonte,
            )
        )
    return out


# ── Rotas (OSRM) e regra do camião ───────────────────────────────────────────

VEL_CAMIAO_KMH = 80
CONDUCAO_ANTES_PAUSA_MIN = 270  # 4h30, Reg. (CE) 561/2006 art. 7.º
PAUSA_MIN = 45
CONDUCAO_DIARIA_MAX_MIN = 540  # 9 h
REPOUSO_DIARIO_MIN = 660  # 11 h


def estimar_camiao(km):
    """(conducao_min, pausas_45min, total_min) com 80 km/h e Reg. 561/2006.

    Uma pausa de 45 min por cada 4h30 de condução completada antes de
    continuar a conduzir. Acima de 9 h de condução soma o repouso diário de
    11 h (não acontece em nenhuma rota da demo).
    """
    cond = km / VEL_CAMIAO_KMH * 60
    pausas = max(0, math.ceil(cond / CONDUCAO_ANTES_PAUSA_MIN) - 1)
    total = cond + pausas * PAUSA_MIN
    if cond > CONDUCAO_DIARIA_MAX_MIN:
        total += math.floor(cond / CONDUCAO_DIARIA_MAX_MIN) * REPOUSO_DIARIO_MIN
    return round(cond, 1), pausas, round(total, 1)


def simplificar(coords, passo_km=1.0):
    """Mantém ~1 ponto por `passo_km` (sempre o primeiro e o último)."""
    if not coords:
        return []
    out, acum = [coords[0]], 0.0
    for a, b in zip(coords, coords[1:]):
        acum += haversine_km(a, b)
        if acum >= passo_km:
            out.append(b)
            acum = 0.0
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return [[round(a, 5), round(b, 5)] for a, b in out]


def t_osrm(
    j,
    origem,
    destino,
    actualizado_em,
    fonte="OSRM demo (router.project-osrm.org), perfil automóvel",
):
    rt = (j.get("routes") or [None])[0]
    if not rt:
        raise ValueError(f"OSRM sem rota {origem}→{destino}: {j.get('code')}")
    km = rt["distance"] / 1000
    coords = [(lat, lon) for lon, lat in rt["geometry"]["coordinates"]]
    cond, pausas, total = estimar_camiao(km)
    return dict(
        origem=origem,
        destino=destino,
        km=round(km, 1),
        duracao_carro_min=round(rt["duration"] / 60, 1),
        conducao_camiao_min=cond,
        pausas_45min=pausas,
        duracao_camiao_estimada_min=total,
        geometria_json=json.dumps(simplificar(coords)),
        actualizado_em=actualizado_em,
        fonte=fonte,
        licenca="demo-nao-comercial",
        nota="OSRM público: uso não-comercial, perfil automóvel. Produção: TomTom Routing "
        "(perfil camião, 20.000 rotas/mês grátis, uso comercial) ou OSRM/ORS alojado por nós.",
    )


# ── Postos perto das rotas (índice em grelha, sem PostGIS) ───────────────────

CEL = 0.05  # graus (~5,5 km em latitude)


def _densificar(coords, passo_km=0.5):
    """[(lat, lon, km_acumulado)] com um vértice a cada ~passo_km."""
    out = [(coords[0][0], coords[0][1], 0.0)]
    acum = 0.0
    for a, b in zip(coords, coords[1:]):
        d = haversine_km(a, b)
        n = max(1, int(d / passo_km))
        for i in range(1, n + 1):
            out.append(
                (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, acum + d * i / n)
            )
        acum += d
    return out


def postos_perto_de_rotas(estacoes, rotas, raio_km=5.0, calculado_em=None):
    """estacoes: linhas de gasolineras_precio; rotas: linhas de rotas_referencia.

    Devolve linhas de gasolineras_rota (um posto pode estar em várias rotas).
    """
    out = []
    for r in rotas:
        coords = json.loads(r["geometria_json"]) if r.get("geometria_json") else []
        if len(coords) < 2:
            continue
        grelha = defaultdict(list)
        for lat, lon, km in _densificar(coords):
            grelha[(int(lat // CEL), int(lon // CEL))].append((lat, lon, km))
        for e in estacoes:
            if e.get("lat") is None or e.get("lon") is None:
                continue
            ci, cj = int(e["lat"] // CEL), int(e["lon"] // CEL)
            melhor = None
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for lat, lon, km in grelha.get((ci + di, cj + dj), ()):
                        d = haversine_km((e["lat"], e["lon"]), (lat, lon))
                        if melhor is None or d < melhor[0]:
                            melhor = (d, km)
            if melhor and melhor[0] <= raio_km:
                out.append(
                    dict(
                        origem=r["origem"],
                        destino=r["destino"],
                        id_estacion=e["id_estacion"],
                        dist_km=round(melhor[0], 2),
                        km_desde_origem=round(melhor[1], 1),
                        calculado_em=calculado_em,
                    )
                )
    return out


# ── Weekly Oil Bulletin (XLSX, só stdlib) ────────────────────────────────────

_NS_X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _col(ref):
    return re.match(r"[A-Z]+", ref).group(0)


def ler_xlsx_primeira_folha(dados):
    """Bytes XLSX → lista de linhas (dict coluna→valor) da 1.ª folha."""
    z = zipfile.ZipFile(io.BytesIO(dados))
    partilhadas = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{_NS_X}si"):
            partilhadas.append("".join(t.text or "" for t in si.iter(f"{_NS_X}t")))
    raiz = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    linhas = []
    for row in raiz.iter(f"{_NS_X}row"):
        vals = {}
        for c in row.findall(f"{_NS_X}c"):
            t = c.get("t")
            if t == "inlineStr":
                x = "".join(e.text or "" for e in c.iter(f"{_NS_X}t"))
            else:
                v = c.find(f"{_NS_X}v")
                x = v.text if v is not None else None
                if t == "s" and x is not None:
                    x = partilhadas[int(x)]
            vals[_col(c.get("r"))] = x
        linhas.append(vals)
    return linhas


def _data_excel(x):
    try:
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(float(x)))
    except (TypeError, ValueError):
        return None


def t_wob(
    dados,
    paises=("ES", "PT", "EU"),
    desde=None,
    fonte="Comissão Europeia, Weekly Oil Bulletin (preços com impostos)",
):
    """XLSX «Prices history» → linhas gasoleo_ue_semanal (€/l)."""
    linhas = ler_xlsx_primeira_folha(dados)
    if not linhas:
        return []
    cab = linhas[0]
    cols = {}
    for col, nome in cab.items():
        if not nome:
            continue
        m = re.match(r"([A-Z]{2,3})_price_with_tax_(diesel|euro95)$", nome.strip())
        if m and m.group(1) in paises:
            cols[(m.group(1), m.group(2))] = col
    out = []
    for lin in linhas[1:]:
        d = _data_excel(lin.get("A"))
        if d is None or (desde and d < desde):
            continue
        for pais in paises:
            di = _f(lin.get(cols.get((pais, "diesel"))))
            ga = _f(lin.get(cols.get((pais, "euro95"))))
            if di is None and ga is None:
                continue
            out.append(
                dict(
                    data=d,
                    pais=pais,
                    gasoleo_eur_l=round(di / 1000, 3) if di else None,
                    gasolina95_eur_l=round(ga / 1000, 3) if ga else None,
                    fonte=fonte,
                )
            )
    return out
