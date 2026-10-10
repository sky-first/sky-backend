# -*- coding: utf-8 -*-
"""
Prova 1 — Gasóleo A mais barato perto de Badajoz e ao longo da A-5 até Madrid.

Fonte:    MITECO / Ministerio para la Transición Ecológica — Geoportal de Gasolineras,
          serviço REST "PreciosCarburantes" (sedeaplicaciones.minetur.gob.es).
          Catálogo: https://www.datos.gob.es/es/catalogo/e05068001-precio-de-carburantes-en-las-gasolineras-espanolas
Licença:  dados abertos do Estado espanhol, reutilização comercial permitida com
          atribuição (Ley 37/2007 / RD 1495/2011). Sem chave, sem limite publicado.
Prova:    que conseguimos responder "onde echo gasóleo más barato en el camino"
          com preço oficial de bomba, por estação, com coordenadas e hora do dado.
Limites:  preço de BOMBA publicado (não o preço com desconto do cartão de frota);
          não indica se o posto aceita camiões; decimais vêm com vírgula.

Uso:  python miteco_gasoleo_a5.py [raio_km]   (omissão: 3 km da rota)
"""
import statistics
import sys

import requests

from _comum import UA, BADAJOZ, Cronometro, densificar, dist_a_rota_km, haversine_km, rota_osrm

BASE = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes"
# Províncias atravessadas pela A-5: Badajoz, Cáceres, Toledo, Madrid
PROVINCIAS = {"06": "Badajoz", "10": "Cáceres", "45": "Toledo", "28": "Madrid"}


def _num(s):
    return float(s.replace(",", ".")) if s else None


def estacoes(provincias=PROVINCIAS):
    """Descarrega as estações das províncias. Devolve (lista, hora_do_dado, ms)."""
    lista, fecha = [], None
    with Cronometro("miteco") as c:
        for cod in provincias:
            r = requests.get(f"{BASE}/EstacionesTerrestres/FiltroProvincia/{cod}", headers=UA, timeout=60)
            r.raise_for_status()
            j = r.json()
            fecha = j.get("Fecha")
            for e in j["ListaEESSPrecio"]:
                p = _num(e.get("Precio Gasoleo A"))
                if not p:
                    continue
                lista.append(dict(
                    nome=e.get("Rótulo", "").strip(), morada=e.get("Dirección", "").strip(),
                    localidade=e.get("Localidad", "").strip(), provincia=e.get("Provincia"),
                    horario=e.get("Horario"), preco=p,
                    lat=_num(e["Latitud"]), lon=_num(e["Longitud (WGS84)"]),
                ))
    return lista, fecha, c.ms


def mais_baratas_na_rota(lista, coords, raio_km=3.0, n=5):
    densa = densificar(coords, 1.0)
    perto = []
    for e in lista:
        d = dist_a_rota_km((e["lat"], e["lon"]), densa)
        if d <= raio_km:
            perto.append({**e, "dist_rota_km": d,
                          "km_desde_origem": haversine_km(coords[0], (e["lat"], e["lon"]))})
    perto.sort(key=lambda e: e["preco"])
    return perto[:n], perto


def main():
    raio = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    lista, fecha, ms = estacoes()
    print(f"MITECO: {len(lista)} estações com Gasóleo A em 4 províncias · dado de {fecha} · {ms} ms")

    # 1) Perto de Badajoz (15 km)
    bjz = sorted([e for e in lista if haversine_km(BADAJOZ, (e["lat"], e["lon"])) <= 15], key=lambda e: e["preco"])
    print(f"\n== Gasóleo A a ≤15 km de Badajoz ({len(bjz)} estações) ==")
    for e in bjz[:5]:
        print(f"  {e['preco']:.3f} €/l  {e['nome'][:28]:28}  {e['localidade'][:22]:22} {e['horario']}")
    if bjz:
        print(f"  Spread: {bjz[0]['preco']:.3f} – {bjz[-1]['preco']:.3f} €/l "
              f"(diferença {100*(bjz[-1]['preco']-bjz[0]['preco']):.1f} cênt./l)")

    # 2) Ao longo da A-5
    rota = rota_osrm()
    top, todas = mais_baratas_na_rota(lista, rota["coords"], raio)
    print(f"\n== Gasóleo A a ≤{raio:g} km da rota Badajoz→Madrid ({len(todas)} estações; rota: {rota['fonte']}) ==")
    for e in top:
        print(f"  {e['preco']:.3f} €/l  {e['nome'][:28]:28}  {e['localidade'][:22]:22} "
              f"~{e['km_desde_origem']:.0f} km de Badajoz (linha reta), a {e['dist_rota_km']:.1f} km da via")
    if todas:
        print("  Mais barata por troço (distância em linha reta desde Badajoz):")
        for ini in range(0, 400, 100):
            t = [e for e in todas if ini <= e["km_desde_origem"] < ini + 100]
            if t:
                b = min(t, key=lambda e: e["preco"])
                print(f"    {ini:3d}-{ini+100:3d} km: {b['preco']:.3f} €/l  {b['nome'][:24]} ({b['localidade'][:20]})")
        precos = [e["preco"] for e in todas]
        print(f"  Spread na rota: mín {min(precos):.3f} · mediana {statistics.median(precos):.3f} · "
              f"máx {max(precos):.3f} €/l")
        print(f"  Encher 600 l no mais barato vs mais caro poupa {600*(max(precos)-min(precos)):.0f} €")
    print("\nNota: preço de bomba publicado no Geoportal; o preço com cartão de frota é outro.")


if __name__ == "__main__":
    main()
