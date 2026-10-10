# -*- coding: utf-8 -*-
"""
Prova 5 — Tempo ao longo da rota Badajoz -> Madrid para a hora de passagem.

Fonte:    Open-Meteo Forecast API (https://api.open-meteo.com/v1/forecast), sem chave.
Licença:  plano grátis SÓ PARA USO NÃO-COMERCIAL (https://open-meteo.com/en/terms);
          dados CC BY 4.0. Usado aqui apenas como TESTE técnico. Em produção: plano
          pago Open-Meteo (Standard) ou AEMET OpenData (comercial permitido, mas exige
          chave por email — não testado aqui por não termos chave sem registo).
Prova:    que, com a rota (OSRM) e a hora de partida, sabemos o tempo previsto em
          cada troço À HORA a que o camião lá passa (1 pedido para vários pontos).
Limites:  previsão por ponto de grelha (~2-11 km), não avisos oficiais (AEMET Meteoalerta).

Uso:  python openmeteo_tempo_rota.py [AAAA-MM-DDTHH:MM]   (omissão: amanhã 06:00)
"""
import datetime as dt
import sys

import requests

from _comum import UA, Cronometro, amostrar, rota_osrm

URL = "https://api.open-meteo.com/v1/forecast"
VARS = "temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,visibility,weather_code"
VEL_CAMIAO_KMH = 78
WMO = {0: "limpo", 1: "pouco nublado", 2: "parcialmente nublado", 3: "encoberto", 45: "nevoeiro",
       48: "nevoeiro c/ geada", 51: "chuvisco", 53: "chuvisco", 55: "chuvisco forte", 61: "chuva fraca",
       63: "chuva", 65: "chuva forte", 71: "neve fraca", 73: "neve", 75: "neve forte", 80: "aguaceiros",
       81: "aguaceiros", 82: "aguaceiros fortes", 95: "trovoada", 96: "trovoada c/ granizo", 99: "trovoada c/ granizo"}


def tempo_na_rota(coords, partida, cada_km=60):
    """Lista de dicts (km, hora, lat, lon, temp, chuva_mm, prob, vento, rajada, visib, ceu) + ms."""
    amostra = amostrar(coords, cada_km)
    pts = [p for p, _ in amostra]
    kms = [k for _, k in amostra]
    params = dict(latitude=",".join(f"{p[0]:.4f}" for p in pts),
                  longitude=",".join(f"{p[1]:.4f}" for p in pts),
                  hourly=VARS, timezone="Europe/Madrid", forecast_days=3, wind_speed_unit="kmh")
    with Cronometro("open-meteo") as c:
        r = requests.get(URL, params=params, headers=UA, timeout=30)
        r.raise_for_status()
    dados = r.json()
    dados = dados if isinstance(dados, list) else [dados]
    out = []
    for p, km, d in zip(pts, kms, dados):
        hora = partida + dt.timedelta(hours=km / VEL_CAMIAO_KMH)
        chave = hora.replace(minute=0).strftime("%Y-%m-%dT%H:00")
        h = d["hourly"]
        if chave not in h["time"]:
            continue
        i = h["time"].index(chave)
        out.append(dict(km=km, hora=hora, lat=p[0], lon=p[1], temp=h["temperature_2m"][i],
                        chuva=h["precipitation"][i], prob=h["precipitation_probability"][i],
                        vento=h["wind_speed_10m"][i], rajada=h["wind_gusts_10m"][i],
                        visib=h["visibility"][i], ceu=WMO.get(h["weather_code"][i], str(h["weather_code"][i]))))
    return out, c.ms


def alertas(linhas):
    a = []
    for l in linhas:
        if l["rajada"] and l["rajada"] >= 60:
            a.append(f"rajadas {l['rajada']:.0f} km/h ao km {l['km']:.0f}")
        if l["visib"] is not None and l["visib"] < 1000:
            a.append(f"visibilidade {l['visib']:.0f} m ao km {l['km']:.0f}")
        if l["chuva"] and l["chuva"] >= 2:
            a.append(f"chuva {l['chuva']} mm/h ao km {l['km']:.0f}")
    return a


def main():
    partida = (dt.datetime.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else
               dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(6, 0)))
    rota = rota_osrm()
    linhas, ms = tempo_na_rota(rota["coords"], partida)
    print(f"Open-Meteo · {len(linhas)} pontos num só pedido · {ms} ms · rota: {rota['fonte']}")
    print(f"Partida {partida:%d/%m/%Y %H:%M} (Europe/Madrid), camião a ~{VEL_CAMIAO_KMH} km/h:")
    for l in linhas:
        print(f"  km {l['km']:5.0f}  {l['hora']:%H:%M}  {l['temp']:5.1f}°C  {l['ceu']:20} "
              f"chuva {l['chuva']:.1f} mm ({l['prob']}%)  vento {l['vento']:.0f}/{l['rajada']:.0f} km/h  "
              f"visib {l['visib']/1000:.1f} km")
    al = alertas(linhas)
    print("Alertas: " + ("; ".join(al) if al else "nenhum (sem chuva forte, rajadas ≥60 km/h ou nevoeiro)"))
    print("Licença: Open-Meteo grátis = só não-comercial. Avisos oficiais: AEMET Meteoalerta (chave).")


if __name__ == "__main__":
    main()
