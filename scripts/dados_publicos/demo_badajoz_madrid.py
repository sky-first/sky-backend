# -*- coding: utf-8 -*-
"""
Prova 7 — Demo combinada (o que o Sky responderia por voz/texto):

  "Voy de Badajoz a Madrid mañana a las 6 con un camión: ¿cuánto tardo, dónde echo
   gasóleo más barato en el camino, qué tiempo hará y hay algún festivo o incidencia?"

Fontes:   OSRM demo (rota, perfil automóvel) · MITECO Geoportal (gasóleo) · Open-Meteo
          (tempo, licença NÃO-comercial, só teste) · Nager.Date (feriados) · DGT DATEX2 v3.7
          (incidências). Ver o cabeçalho de cada script para licenças e limites.
Prova:    que 5 fontes públicas, sem chaves, chegam para uma resposta útil em poucos
          segundos, e quanto tempo isso custa (latência por fonte, em paralelo).
Limites:  tempo de camião é heurística (78 km/h + pausa 561/2006), não routing de camião;
          preço de bomba ≠ preço de cartão de frota; sem restrições DGT a pesados
          (estão em PDF/BOE e ainda não em tabela).
"""
import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor

from _comum import Cronometro, rota_osrm
from dgt_incidencias_a5 import incidencias
from feriados_es_pt import feriados
from miteco_gasoleo_a5 import estacoes, mais_baratas_na_rota
from openmeteo_tempo_rota import alertas, tempo_na_rota
from osrm_rota_badajoz_madrid import estimativa_camiao, hhmm
from _comum import densificar, dist_a_rota_km


def main():
    partida = dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(6, 0))
    t0 = time.perf_counter()
    lat = {}

    # 1) Rota primeiro (as outras fontes dependem da polilinha) + downloads em paralelo
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_rota = ex.submit(rota_osrm)
        f_est = ex.submit(estacoes)
        f_dgt = ex.submit(incidencias)
        f_fer_es = ex.submit(feriados, partida.year, "ES")
        f_fer_pt = ex.submit(feriados, partida.year, "PT")
        rota = f_rota.result()
        f_tempo = ex.submit(tempo_na_rota, rota["coords"], partida)
        lista, fecha_miteco, lat["MITECO"] = f_est.result()
        dgt, lat["DGT"] = f_dgt.result()
        (fer_es, lat["Nager ES"]), (fer_pt, _) = f_fer_es.result(), f_fer_pt.result()
        tempo, lat["Open-Meteo"] = f_tempo.result()
    lat["OSRM"] = rota["ms"]
    with Cronometro("calculo") as calc:
        top, todas = mais_baratas_na_rota(lista, rota["coords"], 3.0, n=3)
        densa = densificar(rota["coords"], 1.0)
        inc = [
            i
            for i in dgt
            if i["estado"] in (None, "active")
            and i["coord"]
            and dist_a_rota_km(i["coord"], densa) <= 1.0
        ]
    lat["cálculo local"] = calc.ms
    total_ms = int((time.perf_counter() - t0) * 1000)

    dia, seguinte = partida.date().isoformat(), (partida.date() + dt.timedelta(days=1)).isoformat()
    fest_hoje = [
        h["localName"]
        for h in fer_es
        if h["date"] == dia
        and (h.get("global") or set(h.get("counties") or []) & {"ES-EX", "ES-MD"})
    ]
    fest_amanha = [h["localName"] for h in fer_es if h["date"] == seguinte and h.get("global")]

    print("=" * 78)
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    print(
        f"Pergunta: Badajoz → Madrid, {dias[partida.weekday()]} {partida:%d/%m/%Y} às {partida:%H:%M}, camião"
    )
    print("=" * 78)
    if rota["distancia_km"]:
        cond, pausas, tot = estimativa_camiao(rota["distancia_km"])
        cheg = partida + dt.timedelta(minutes=tot)
        print(
            f"🚛 Tempo: {rota['distancia_km']:.0f} km pela A-5 (sem portagens). Ligeiro: {hhmm(rota['duracao_min'])}. "
            f"Camião (estimativa): {hhmm(cond)} de condução + {pausas}×45 min de pausa → chegada ~{cheg:%H:%M}."
        )
    print(f"⛽ Gasóleo A mais barato a ≤3 km da rota ({len(todas)} postos; MITECO {fecha_miteco}):")
    for e in top:
        print(
            f"     {e['preco']:.3f} €/l  {e['nome'][:26]} — {e['localidade'].title()[:24]} ({e['horario']})"
        )
    if todas:
        p = [e["preco"] for e in todas]
        print(
            f"     Diferença mais barato/mais caro na rota: {100*(max(p)-min(p)):.0f} cênt./l "
            f"(≈ {600*(max(p)-min(p)):.0f} € num depósito de 600 l)."
        )
    print("🌦  Tempo à hora de passagem (Open-Meteo):")
    if tempo:
        tmin, tmax = min(l["temp"] for l in tempo), max(l["temp"] for l in tempo)
        ceus = sorted({l["ceu"] for l in tempo})
        al = alertas(tempo)
        print(
            f"     {tmin:.0f}–{tmax:.0f} °C, {', '.join(ceus)}; chuva máx {max(l['chuva'] for l in tempo):.1f} mm/h; "
            f"rajada máx {max(l['rajada'] for l in tempo):.0f} km/h. "
            f"{'Alertas: ' + '; '.join(al) if al else 'Sem alertas.'}"
        )
    print(
        "📅 Feriados:",
        (
            ", ".join(fest_hoje)
            if fest_hoje
            else f"{partida:%d/%m} não é feriado (ES/Extremadura/Madrid)."
        ),
        (
            f"⚠ Véspera de feriado nacional: {', '.join(fest_amanha)} — confirmar restrições DGT a pesados."
            if fest_amanha
            else ""
        ),
    )
    if partida.weekday() == 6:
        print(
            "     ⚠ É domingo: a DGT restringe pesados em certos troços/horas (resolução 2026, ainda não carregada)."
        )
    print(f"🚧 Incidências DGT ativas a ≤1 km da rota agora: {len(inc)}")
    for i in inc[:5]:
        print(
            f"     {i['estrada']} PK {i['pk']} {i['municipio']} — {i['causa'] or i['tipo']} (desde {(i['inicio'] or '')[11:16]})"
        )
    print("-" * 78)
    print(
        "Latência por fonte (ms): "
        + " · ".join(f"{k} {v}" for k, v in lat.items())
        + f"  →  total em paralelo {total_ms} ms"
    )
    print(
        "Fontes: OSRM/OSM (ODbL), MITECO, Open-Meteo (CC BY, não-comercial), Nager.Date, DGT NAP."
    )


if __name__ == "__main__":
    main()
