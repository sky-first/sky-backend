# -*- coding: utf-8 -*-
"""
Utilitários partilhados pelos scripts de prova de dados públicos.

- Rota Badajoz -> Madrid (A-5): pede a geometria ao OSRM público (demo, perfil
  de AUTOMÓVEL, sem garantias de disponibilidade nem uso comercial). Se falhar,
  usa pontos fixos da A-5 escritos à mão.
- Distância haversine, medição de latência e saída UTF-8 no Windows.

Só stdlib + requests. Sem chaves.
"""
import math
import sys
import time

import requests

try:  # consola do Windows (cp1252) não imprime acentos sem isto
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = {"User-Agent": "SkyFirst-prova-dados-publicos/1.0 (+https://skyfirstlabs.com)"}

BADAJOZ = (38.8794, -6.9707)
MADRID = (40.4168, -3.7038)

# Pontos da A-5 (fallback se o OSRM falhar): lat, lon, nome
A5_PONTOS = [
    (38.8794, -6.9707, "Badajoz"),
    (38.9161, -6.3437, "Mérida"),
    (39.1520, -5.9070, "Miajadas"),
    (39.4597, -5.8819, "Trujillo"),
    (39.8838, -5.5407, "Navalmoral de la Mata"),
    (39.9196, -5.1740, "Oropesa"),
    (39.9635, -4.8306, "Talavera de la Reina"),
    (40.0679, -4.3714, "Maqueda"),
    (40.2190, -4.0153, "Navalcarnero"),
    (40.4168, -3.7038, "Madrid"),
]


def haversine_km(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(d))


class Cronometro:
    """with Cronometro('fonte') as c: ...  ->  c.ms"""

    def __init__(self, nome):
        self.nome = nome
        self.ms = 0

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self.t0) * 1000)


def rota_osrm(origem=BADAJOZ, destino=MADRID, timeout=30):
    """Devolve dict(distancia_km, duracao_min, coords=[(lat,lon),...], fonte, ms)."""
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{origem[1]},{origem[0]};{destino[1]},{destino[0]}"
        "?overview=simplified&geometries=geojson"
    )
    with Cronometro("osrm") as c:
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
            r.raise_for_status()
            rt = r.json()["routes"][0]
            coords = [(lat, lon) for lon, lat in rt["geometry"]["coordinates"]]
            res = dict(distancia_km=rt["distance"] / 1000, duracao_min=rt["duration"] / 60,
                       coords=coords, fonte="OSRM demo (perfil automóvel)")
        except Exception as e:  # fallback: pontos fixos
            res = dict(distancia_km=None, duracao_min=None,
                       coords=[(a, b) for a, b, _ in A5_PONTOS], fonte=f"pontos fixos A-5 (OSRM falhou: {e})")
    res["ms"] = c.ms
    return res


def amostrar(coords, cada_km=40):
    """Um ponto a cada ~cada_km ao longo da polilinha. Devolve [((lat,lon), km_na_rota), ...]."""
    out, acum, desde = [(coords[0], 0.0)], 0.0, 0.0
    for a, b in zip(coords, coords[1:]):
        d = haversine_km(a, b)
        acum += d
        desde += d
        if desde >= cada_km:
            out.append((b, acum))
            desde = 0.0
    if out[-1][0] != coords[-1]:
        out.append((coords[-1], acum))
    return out


def dist_a_rota_km(ponto, coords):
    """Distância mínima (aprox.) de um ponto aos vértices da polilinha."""
    return min(haversine_km(ponto, c) for c in coords)


def densificar(coords, passo_km=1.0):
    """Interpola vértices para que a distância a 'vértices' seja próxima da distância à linha."""
    out = [coords[0]]
    for a, b in zip(coords, coords[1:]):
        d = haversine_km(a, b)
        n = max(1, int(d / passo_km))
        for i in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n))
    return out
