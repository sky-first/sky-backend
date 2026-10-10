# -*- coding: utf-8 -*-
"""
Prova 2 — Distância e tempo Badajoz -> Madrid, com estimativa para camião.

Fonte:    OSRM, servidor de demonstração público (router.project-osrm.org), dados OpenStreetMap.
          https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server
Licença:  software BSD-2; dados OSM ODbL (atribuição "© OpenStreetMap contributors").
          O servidor DEMO não tem SLA e a política proíbe uso pesado/produtivo — serve
          só para esta prova. Produção: OSRM/ORS self-hosted ou TomTom (perfil camião).
          openrouteservice foi testado SEM chave: HTTP 401 "Authorization field missing"
          (exige chave gratuita; não a pusemos no ficheiro, por regra).
Prova:    que temos distância e tempo de viagem por pedido, em <1 s.
Limite:   perfil AUTOMÓVEL. Não conhece velocidade máxima de pesados (90 km/h em
          autovía para camiões em ES), peso, altura, restrições DGT nem trânsito.
          A estimativa "camião" abaixo é uma heurística nossa, não do OSRM.
"""
import requests

from _comum import UA, BADAJOZ, MADRID, Cronometro, rota_osrm

VEL_MEDIA_CAMIAO_KMH = 78  # média realista p/ articulado 40 t em autovía (limite legal 90)
CONDUCAO_ANTES_PAUSA_H = 4.5  # Reg. (CE) 561/2006, art. 7.º: pausa de 45 min após 4h30
PAUSA_MIN = 45


def hhmm(minutos):
    h, m = divmod(int(round(minutos)), 60)
    return f"{h}h{m:02d}"


def estimativa_camiao(distancia_km):
    conducao_min = distancia_km / VEL_MEDIA_CAMIAO_KMH * 60
    pausas = int(conducao_min // (CONDUCAO_ANTES_PAUSA_H * 60))
    if conducao_min % (CONDUCAO_ANTES_PAUSA_H * 60) == 0 and pausas:
        pausas -= 1
    return conducao_min, pausas, conducao_min + pausas * PAUSA_MIN


def ors_sem_chave():
    """Confirma se o openrouteservice aceita pedidos sem chave (esperado: não)."""
    url = (
        f"https://api.openrouteservice.org/v2/directions/driving-hgv?"
        f"start={BADAJOZ[1]},{BADAJOZ[0]}&end={MADRID[1]},{MADRID[0]}"
    )
    with Cronometro("ors") as c:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            estado = f"HTTP {r.status_code} {' '.join(r.text.split())[:60]}"
        except Exception as e:
            estado = f"erro {e}"
    return estado, c.ms


def main():
    r = rota_osrm()
    if r["distancia_km"] is None:
        print(f"OSRM indisponível: {r['fonte']}")
        return
    print(f"OSRM ({r['fonte']}) · {r['ms']} ms")
    print(
        f"  Badajoz → Madrid: {r['distancia_km']:.1f} km · {hhmm(r['duracao_min'])} (automóvel, sem trânsito)"
    )
    cond, pausas, total = estimativa_camiao(r["distancia_km"])
    print(
        f"  Estimativa camião 40 t (heurística {VEL_MEDIA_CAMIAO_KMH} km/h): condução {hhmm(cond)}"
        f" + {pausas} pausa(s) de {PAUSA_MIN} min = {hhmm(total)}"
    )
    print(f"  Partida 06:00 → chegada estimada ~{hhmm(6*60 + total).replace('h', ':')}")
    estado, ms = ors_sem_chave()
    print(f"\nopenrouteservice driving-hgv sem chave: {estado} · {ms} ms")
    print(
        "Limite: OSRM demo = perfil automóvel e sem SLA; para camião real usar TomTom/HERE/ORS-hgv."
    )


if __name__ == "__main__":
    main()
