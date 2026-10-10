# -*- coding: utf-8 -*-
"""
Prova 6 — Incidências DGT agora: na A-5, na província de Badajoz e junto à rota.

Fonte:    DGT, Punto de Acceso Nacional (NAP), "Incidencias DGT DATEX2 v3.7"
          https://nap.dgt.es/en/dataset/incidencias-dgt-datex2-v3-7
          Feed: https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml
Licença:  dados de tráfego de acesso livre (Reg. Delegado UE 886/2013 / SRTI e 2022/670);
          reutilização permitida com atribuição à DGT. Sem chave. Atualização ~1 min.
          Cobre a rede da DGT (fora País Basco e Catalunha, que têm feeds próprios).
Prova:    que respondemos "¿hay alguna incidencia en la A-5 ahora?" com causa, troço,
          PK e município, a partir de dado oficial em XML (~3 MB, ~2 s).
Limites:  "incidência" inclui obras de longa duração e estreitamentos; filtramos por
          estado "active". Portugal não tem feed equivalente público encontrado.
"""
import collections
import xml.etree.ElementTree as ET

import requests

from _comum import UA, Cronometro, densificar, dist_a_rota_km, rota_osrm

URL = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _primeiro(el, nome):
    for e in el.iter():
        if _local(e.tag) == nome:
            return (e.text or "").strip()
    return None


def incidencias():
    """Lista de dicts por situationRecord + ms."""
    with Cronometro("dgt") as c:
        r = requests.get(URL, headers=UA, timeout=60)
        r.raise_for_status()
        raiz = ET.fromstring(r.content)
    out = []
    for rec in raiz.iter():
        if _local(rec.tag) != "situationRecord":
            continue
        lat, lon = _primeiro(rec, "latitude"), _primeiro(rec, "longitude")
        out.append(
            dict(
                tipo=(rec.get(XSI_TYPE) or "").split(":")[-1],
                causa=_primeiro(rec, "causeType"),
                estado=_primeiro(rec, "validityStatus"),
                estrada=_primeiro(rec, "roadName"),
                provincia=_primeiro(rec, "province"),
                municipio=_primeiro(rec, "municipality"),
                pk=_primeiro(rec, "kilometerPoint"),
                inicio=_primeiro(rec, "overallStartTime"),
                coord=(float(lat), float(lon)) if lat and lon else None,
            )
        )
    return out, c.ms


def resumo(lista, titulo, n=6):
    print(f"\n== {titulo}: {len(lista)} ==")
    cont = collections.Counter(f"{i['tipo']}/{i['causa'] or '-'}" for i in lista)
    for k, v in cont.most_common():
        print(f"  {v:3d} × {k}")
    for i in lista[:n]:
        print(
            f"  · {i['estrada'] or '?':7} PK {i['pk'] or '?':>6}  {i['municipio'] or '?'} ({i['provincia'] or '?'})"
            f"  {i['causa'] or i['tipo']}  desde {(i['inicio'] or '')[:16]}"
        )


def main():
    todas, ms = incidencias()
    ativas = [i for i in todas if i["estado"] in (None, "active")]
    print(f"DGT DATEX2 v3.7 · {len(todas)} registos ({len(ativas)} ativos) em Espanha · {ms} ms")
    resumo([i for i in ativas if i["estrada"] == "A-5"], "Ativas na A-5")
    resumo(
        [i for i in ativas if (i["provincia"] or "").lower() == "badajoz"],
        "Ativas na província de Badajoz",
    )
    rota = rota_osrm()
    densa = densificar(rota["coords"], 1.0)
    junto = [i for i in ativas if i["coord"] and dist_a_rota_km(i["coord"], densa) <= 1.0]
    resumo(junto, f"Ativas a ≤1 km da rota Badajoz→Madrid ({rota['fonte']})")
    print("\nNota: inclui obras e estreitamentos de longa duração; ver 'desde'.")


if __name__ == "__main__":
    main()
