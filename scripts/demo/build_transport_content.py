# -*- coding: utf-8 -*-
"""Conteúdo curado do sector Logística e Transportes.

Mesma razão dos outros construtores: o SQL é partilhado pelos dois
idiomas e só o texto muda. Ver `build_distribution_content.py`.

    python scripts/demo/build_transport_content.py
    python scripts/demo/build_es_content.py
    python scripts/curate_demo_content.py --verify-sql --apply

── Porque é que este sector existe ─────────────────────────────────

A demo pública oferecia quatro sectores e nenhum deles é transporte.
Quem move mercadoria para viver não se revê em "lugares de subscrição"
nem em "horas faturáveis" — e os três primeiros clientes à espera de
ver a plataforma são transportadoras.

── O custo por quilómetro é uma margem de contribuição ─────────────

O custo aqui é gasóleo + motorista + portagens + oficina + o custo fixo
da viatura (leasing, seguro, imposto). **Não inclui** a estrutura:
armazém, tráfego, administrativo, comercial. Portanto o que a diferença
entre receita/km e custo/km mede é a *contribuição* da viatura, não o
lucro da empresa — e é exactamente assim que um gestor de frota o mede.

Dizer "lucro" seria mais vendedor e seria mentira; a primeira pessoa a
notá-lo seria o director financeiro que temos à frente.
"""

from __future__ import annotations

import json
from pathlib import Path

ALVO = Path(__file__).resolve().parents[2] / "scripts" / "demo" / "curated_content.json"

# ── SQL ──────────────────────────────────────────────────────────────

# O custo completo por viatura. As quatro parcelas vivem em sítios
# diferentes na vida real — cartão de combustível, tacógrafo, via verde,
# oficina — e é por isso que ninguém tem este quadro.
SQL_CUSTO_KM = """WITH custo AS (
    SELECT t.vehicle_id,
           SUM(t.km_run) AS km,
           SUM(t.fuel_litres * 1.62
               + t.driver_hours * d.cost_per_hour
               + r.toll_cost) AS running_cost
    FROM ops.trips t
    JOIN fleet.drivers d ON d.id = t.driver_id
    JOIN ops.routes r ON r.id = t.route_id
    WHERE t.status = 'completed'
    GROUP BY t.vehicle_id
), workshop AS (
    SELECT vehicle_id, SUM(cost) AS workshop_cost, SUM(days_off_road) AS days_off
    FROM fleet.maintenance_jobs GROUP BY vehicle_id
), income AS (
    SELECT t.vehicle_id, SUM(s.revenue) AS revenue
    FROM ops.trips t JOIN freight.shipments s ON s.trip_id = t.id
    GROUP BY t.vehicle_id
)
SELECT v.plate,
       EXTRACT(YEAR FROM v.acquired_on)::INT AS year,
       c.km,
       ROUND((c.running_cost + COALESCE(w.workshop_cost, 0)
              + v.fixed_cost_month * 12) / NULLIF(c.km, 0), 3) AS cost_per_km,
       ROUND(COALESCE(i.revenue, 0) / NULLIF(c.km, 0), 3) AS revenue_per_km,
       ROUND(COALESCE(i.revenue, 0)
             - (c.running_cost + COALESCE(w.workshop_cost, 0)
                + v.fixed_cost_month * 12)) AS contribution
FROM fleet.vehicles v
JOIN custo c ON c.vehicle_id = v.id
LEFT JOIN workshop w ON w.vehicle_id = v.id
LEFT JOIN income i ON i.vehicle_id = v.id
ORDER BY contribution"""

# O retorno vazio, troço a troço. É a pergunta que paga a plataforma:
# não há nenhum sistema onde esta linha exista.
SQL_VAZIO = """SELECT r.origin || ' - ' || r.destination AS leg,
       r.distance_km,
       COUNT(*) AS trips,
       COUNT(*) FILTER (WHERE s.id IS NULL) AS empty_trips,
       SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END) AS empty_km,
       ROUND(SUM(CASE WHEN s.id IS NULL THEN t.fuel_litres * 1.62 ELSE 0 END)) AS fuel_burned
FROM ops.trips t
JOIN ops.routes r ON r.id = t.route_id
LEFT JOIN freight.shipments s ON s.trip_id = t.id
WHERE t.status = 'completed'
GROUP BY r.id, leg, r.distance_km
HAVING COUNT(*) FILTER (WHERE s.id IS NULL) > 0
ORDER BY fuel_burned DESC"""

# Pontualidade contra o SLA do CLIENTE, não contra uma hora fixa. O
# mesmo atraso de 40 minutos é indiferente para a construção e é uma
# penalização no frio.
SQL_SLA = """SELECT r.origin || ' - ' || r.destination AS leg,
       r.distance_km,
       r.standard_minutes,
       COUNT(*) AS trips,
       ROUND(100.0 * COUNT(*) FILTER (
             WHERE t.arrived_at > t.planned_arrival
                   + (c.sla_minutes * INTERVAL '1 minute'))
             / COUNT(*), 1) AS pct_outside_sla,
       ROUND(AVG(EXTRACT(EPOCH FROM (t.arrived_at - t.planned_arrival)) / 60)) AS avg_delay_min
FROM ops.trips t
JOIN ops.routes r ON r.id = t.route_id
JOIN freight.shipments s ON s.trip_id = t.id
JOIN freight.clients c ON c.id = s.client_id
WHERE t.status = 'completed'
GROUP BY r.id, leg, r.distance_km, r.standard_minutes
ORDER BY pct_outside_sla DESC"""

SQL_CLIENTES = """SELECT c.name, c.sector, c.sla_minutes,
       COUNT(*) AS shipments,
       ROUND(SUM(s.revenue)) AS revenue,
       ROUND(SUM(s.revenue) / NULLIF(SUM(t.km_run), 0), 2) AS revenue_per_km,
       COUNT(*) FILTER (WHERE s.incident IS NOT NULL) AS incidents
FROM freight.shipments s
JOIN ops.trips t ON t.id = s.trip_id
JOIN freight.clients c ON c.id = s.client_id
GROUP BY c.id, c.name, c.sector, c.sla_minutes
ORDER BY revenue_per_km DESC"""

SQL_OFICINA = """SELECT v.plate,
       EXTRACT(YEAR FROM v.acquired_on)::INT AS year,
       COUNT(*) FILTER (WHERE m.kind = 'avaria') AS breakdowns,
       COUNT(*) FILTER (WHERE m.kind = 'preventiva') AS preventive,
       ROUND(SUM(m.cost)) AS workshop_cost,
       SUM(m.days_off_road) AS days_off_road
FROM fleet.vehicles v
JOIN fleet.maintenance_jobs m ON m.vehicle_id = v.id
GROUP BY v.id, v.plate, v.acquired_on
ORDER BY workshop_cost DESC"""

SQL_MOTORISTAS = """SELECT d.name, d.licence,
       COUNT(*) AS trips,
       ROUND(SUM(t.driver_hours)) AS hours,
       ROUND(SUM(t.km_run)) AS km,
       ROUND(100.0 * COUNT(*) FILTER (WHERE t.arrived_at <= t.planned_arrival)
             / COUNT(*), 1) AS pct_on_standard
FROM ops.trips t
JOIN fleet.drivers d ON d.id = t.driver_id
WHERE t.status = 'completed'
GROUP BY d.id, d.name, d.licence
ORDER BY hours DESC"""

# ── séries ───────────────────────────────────────────────────────────

SQL_SERIE_VAZIO = """SELECT DATE_TRUNC('month', t.departed_at)::date AS t,
       ROUND(100.0 * SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END)
             / NULLIF(SUM(t.km_run), 0), 1) AS v
FROM ops.trips t
LEFT JOIN freight.shipments s ON s.trip_id = t.id
WHERE t.status = 'completed'
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_SLA = """SELECT DATE_TRUNC('month', t.departed_at)::date AS t,
       ROUND(100.0 * COUNT(*) FILTER (
             WHERE t.arrived_at <= t.planned_arrival
                   + (c.sla_minutes * INTERVAL '1 minute'))
             / COUNT(*), 1) AS v
FROM ops.trips t
JOIN freight.shipments s ON s.trip_id = t.id
JOIN freight.clients c ON c.id = s.client_id
WHERE t.status = 'completed'
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_CONTRIBUICAO = """WITH custo AS (
    SELECT t.vehicle_id, SUM(t.km_run) AS km,
           SUM(t.fuel_litres * 1.62 + t.driver_hours * d.cost_per_hour
               + r.toll_cost) AS running_cost
    FROM ops.trips t
    JOIN fleet.drivers d ON d.id = t.driver_id
    JOIN ops.routes r ON r.id = t.route_id
    WHERE t.status = 'completed'
    GROUP BY t.vehicle_id
), workshop AS (
    SELECT vehicle_id, SUM(cost) AS workshop_cost
    FROM fleet.maintenance_jobs GROUP BY vehicle_id
), income AS (
    SELECT t.vehicle_id, SUM(s.revenue) AS revenue
    FROM ops.trips t JOIN freight.shipments s ON s.trip_id = t.id
    GROUP BY t.vehicle_id
)
SELECT v.plate AS t,
       ROUND(COALESCE(i.revenue, 0)
             - (c.running_cost + COALESCE(w.workshop_cost, 0)
                + v.fixed_cost_month * 12)) AS v
FROM fleet.vehicles v
JOIN custo c ON c.vehicle_id = v.id
LEFT JOIN workshop w ON w.vehicle_id = v.id
LEFT JOIN income i ON i.vehicle_id = v.id
ORDER BY v"""

# ── valores escalares ────────────────────────────────────────────────
#
# Cada um devolve UM número. O `--verify-sql` corre-os contra a base
# sintética e recusa publicar o que rebentar — é por isso que os números
# dos cartões não envelhecem em silêncio.

_CUSTO_TOTAL = (
    "(c.running_cost + COALESCE(w.workshop_cost, 0) + v.fixed_cost_month * 12)"
)
_BASE_FROTA = f"""WITH custo AS (
    SELECT t.vehicle_id, SUM(t.km_run) AS km,
           SUM(t.fuel_litres * 1.62 + t.driver_hours * d.cost_per_hour
               + r.toll_cost) AS running_cost
    FROM ops.trips t
    JOIN fleet.drivers d ON d.id = t.driver_id
    JOIN ops.routes r ON r.id = t.route_id
    WHERE t.status = 'completed' GROUP BY t.vehicle_id
), workshop AS (
    SELECT vehicle_id, SUM(cost) AS workshop_cost
    FROM fleet.maintenance_jobs GROUP BY vehicle_id
), income AS (
    SELECT t.vehicle_id, SUM(s.revenue) AS revenue
    FROM ops.trips t JOIN freight.shipments s ON s.trip_id = t.id
    GROUP BY t.vehicle_id
), frota AS (
    SELECT v.plate, c.km,
           {_CUSTO_TOTAL} AS total_cost,
           COALESCE(i.revenue, 0) AS revenue,
           COALESCE(i.revenue, 0) - {_CUSTO_TOTAL} AS contribution
    FROM fleet.vehicles v
    JOIN custo c ON c.vehicle_id = v.id
    LEFT JOIN workshop w ON w.vehicle_id = v.id
    LEFT JOIN income i ON i.vehicle_id = v.id
)"""

_VAZIO_FROM = (
    "FROM ops.trips t LEFT JOIN freight.shipments s ON s.trip_id = t.id "
    "WHERE t.status = 'completed'"
)
_SLA_FROM = (
    "FROM ops.trips t JOIN freight.shipments s ON s.trip_id = t.id "
    "JOIN freight.clients c ON c.id = s.client_id WHERE t.status = 'completed'"
)

V = {
    # frota
    "custo_km_medio": f"{_BASE_FROTA} SELECT ROUND(SUM(total_cost) / NULLIF(SUM(km), 0), 2) FROM frota",
    "receita_km_media": f"{_BASE_FROTA} SELECT ROUND(SUM(revenue) / NULLIF(SUM(km), 0), 2) FROM frota",
    "pior_viatura": f"{_BASE_FROTA} SELECT plate FROM frota ORDER BY contribution LIMIT 1",
    # A diferença entre a metade de cima e a metade de baixo da frota. É
    # o número que fecha a conversa: não é "uma viatura está má", é "meia
    # frota traz isto a menos do que a outra meia, todos os anos".
    "diferenca_contribuicao": (
        f"{_BASE_FROTA} SELECT ROUND((SELECT AVG(contribution) FROM frota "
        "WHERE contribution > (SELECT AVG(contribution) FROM frota)) "
        "- (SELECT AVG(contribution) FROM frota "
        "WHERE contribution <= (SELECT AVG(contribution) FROM frota)))"
    ),
    # vazio
    "km_vazio": f"SELECT COALESCE(SUM(t.km_run), 0) {_VAZIO_FROM} AND s.id IS NULL",
    "km_vazio_pct": (
        "SELECT ROUND(100.0 * SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END)"
        f" / NULLIF(SUM(t.km_run), 0), 1) {_VAZIO_FROM}"
    ),
    "gasoleo_vazio": (
        "SELECT COALESCE(ROUND(SUM(t.fuel_litres * 1.62)), 0) "
        f"{_VAZIO_FROM} AND s.id IS NULL"
    ),
    "troco_mais_vazio": (
        "SELECT r.origin || ' - ' || r.destination FROM ops.trips t "
        "JOIN ops.routes r ON r.id = t.route_id "
        "LEFT JOIN freight.shipments s ON s.trip_id = t.id "
        "WHERE t.status = 'completed' AND s.id IS NULL "
        "GROUP BY r.id, r.origin, r.destination "
        "ORDER BY SUM(t.fuel_litres * 1.62) DESC LIMIT 1"
    ),
    # pontualidade
    "pontualidade": (
        "SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE t.arrived_at <= t.planned_arrival"
        f" + (c.sla_minutes * INTERVAL '1 minute')) / COUNT(*), 1) {_SLA_FROM}"
    ),
    "portes_fora_sla": (
        "SELECT COUNT(*) " + _SLA_FROM + " AND t.arrived_at > t.planned_arrival"
        " + (c.sla_minutes * INTERVAL '1 minute')"
    ),
    "pior_rota": (
        "SELECT r.origin || ' - ' || r.destination FROM ops.trips t "
        "JOIN ops.routes r ON r.id = t.route_id "
        "JOIN freight.shipments s ON s.trip_id = t.id "
        "JOIN freight.clients c ON c.id = s.client_id "
        "WHERE t.status = 'completed' GROUP BY r.id, r.origin, r.destination "
        "ORDER BY 100.0 * COUNT(*) FILTER (WHERE t.arrived_at > t.planned_arrival"
        " + (c.sla_minutes * INTERVAL '1 minute')) / COUNT(*) DESC LIMIT 1"
    ),
    # oficina e carga
    "oficina_total": "SELECT COALESCE(ROUND(SUM(cost)), 0) FROM fleet.maintenance_jobs",
    "dias_fora_estrada": "SELECT COALESCE(SUM(days_off_road), 0) FROM fleet.maintenance_jobs",
    "avarias": "SELECT COUNT(*) FROM fleet.maintenance_jobs WHERE kind = 'avaria'",
    "receita_total": "SELECT COALESCE(ROUND(SUM(revenue)), 0) FROM freight.shipments",
    "viagens": "SELECT COUNT(*) FROM ops.trips WHERE status = 'completed'",
    "incidentes": "SELECT COUNT(*) FROM freight.shipments WHERE incident IS NOT NULL",
    "cliente_melhor_km": (
        "SELECT c.name FROM freight.shipments s JOIN ops.trips t ON t.id = s.trip_id "
        "JOIN freight.clients c ON c.id = s.client_id GROUP BY c.id, c.name "
        "ORDER BY SUM(s.revenue) / NULLIF(SUM(t.km_run), 0) DESC LIMIT 1"
    ),
    "motorista_mais_horas": (
        "SELECT d.name FROM ops.trips t JOIN fleet.drivers d ON d.id = t.driver_id "
        "WHERE t.status = 'completed' GROUP BY d.id, d.name "
        "ORDER BY SUM(t.driver_hours) DESC LIMIT 1"
    ),
}

# As fontes, nos dois idiomas. Estão à vista no cartão de propósito: é o
# que separa isto de um gerador de texto.
_FONTES = [
    ("ops.trips", "Cada viagem: km, gasóleo, horas, chegada",
     "Every trip: km, fuel, hours, arrival"),
    ("freight.shipments", "A carga que seguiu, e por quanto",
     "The load that went, and for how much"),
    ("fleet.vehicles", "A viatura, e o que custa tê-la",
     "The vehicle, and what it costs to have it"),
    ("fleet.maintenance_jobs", "Oficina: avaria, preventiva, dias parado",
     "Workshop: breakdown, preventive, days off road"),
    ("ops.routes", "Distância, tempo padrão e portagens",
     "Distance, standard time and tolls"),
    ("freight.clients", "Quem paga, e com que tolerância contratada",
     "Who pays, and with what contracted tolerance"),
]


def fontes(pt):
    return [{"table": t, "description": (a if pt else b)} for t, a, b in _FONTES]


def tile(rotulo, chave, formato=None):
    t = {"label": rotulo, "value_sql": V[chave]}
    if formato:
        t["format"] = formato
    return t


def dataset(locale):
    pt = locale == "pt"
    L = lambda a, b: a if pt else b  # noqa: E731
    F = fontes(pt)

    return {
        "vertical": "transport",
        "locale": locale,
        "is_default": False,
        "name": L("Transportes Guadiana — 18 viaturas",
                  "Guadiana Haulage — 18 vehicles"),
        "description": L(
            "Transportadora ibérica com 18 viaturas, 20 rotas entre Portugal e "
            "Espanha e 12 meses de viagens.",
            "Iberian haulier with 18 vehicles, 20 routes between Portugal and "
            "Spain and 12 months of trips."),
        "connection_ref": L("Demo — Transportes", "Demo — Transport"),
        "insight": {
            "severity": "fleet_contribution",
            "severity_level": "warning",
            "agent_name": L("Frota", "Fleet"),
            "title": L("Três viaturas custam por quilómetro quase o que rendem",
                       "Three vehicles cost nearly per kilometre what they earn"),
            "summary": L(
                "São as mais velhas, e continuam a ser escaladas porque já estão pagas. "
                "A prestação acabou, por isso o custo fixo é baixo — e é esse número "
                "baixo que faz parecer que compensa mantê-las.\n\n"
                "O que não aparece em lado nenhum é a soma do resto: gastam mais um "
                "terço de gasóleo por quilómetro, entram na oficina várias vezes por "
                "ano, e passam semanas fora da estrada. Cada parcela está num sistema "
                "diferente — cartão de combustível, factura da oficina, mapa de "
                "serviço — e nenhuma delas, sozinha, parece um problema.\n\n"
                "É a diferença entre receita e custo por quilómetro, viatura a viatura. "
                "Não é o lucro da empresa: a estrutura não está aqui. É o que cada "
                "camião traz depois de pagar o que ele próprio consome.",
                "They are the oldest, and they keep being dispatched because they are "
                "paid off. The lease is over, so the fixed cost is low — and it is that "
                "low number that makes keeping them look sensible.\n\n"
                "What appears nowhere is the sum of the rest: they burn a third more "
                "diesel per kilometre, go into the workshop several times a year, and "
                "spend weeks off the road. Each piece lives in a different system — fuel "
                "card, workshop invoice, duty roster — and none of them, on its own, "
                "looks like a problem.\n\n"
                "This is revenue minus cost per kilometre, vehicle by vehicle. It is not "
                "company profit: overheads are not in here. It is what each truck brings "
                "once it has paid for what it consumes itself."),
            "stat_tiles": [
                tile(L("Custo médio por km", "Average cost per km"), "custo_km_medio", "eur"),
                tile(L("Receita média por km", "Average revenue per km"), "receita_km_media", "eur"),
                tile(L("A pior delas", "The worst of them"), "pior_viatura"),
            ],
            "sources": [F[2], F[0], F[3], F[1]],
            "executed_sql": SQL_CUSTO_KM,
            "series_sql": SQL_SERIE_CONTRIBUICAO,
        },
        "extra_insights": [
            {
                "severity": "empty_running",
                "severity_level": "warning",
                "agent_name": L("Tráfego", "Traffic"),
                "title": L("Um quinto dos quilómetros é andado sem carga nenhuma",
                           "A fifth of the kilometres are run with nothing on board"),
                "summary": L(
                    "O retorno vazio é o custo mais invisível desta indústria. Aparece "
                    "todo no gasóleo e não aparece em lado nenhum na faturação — "
                    "portanto não há nenhum relatório onde ele seja uma linha.\n\n"
                    "Ninguém o nega e ninguém sabe quanto é. O número só existe "
                    "cruzando as viagens com a carga: a viagem está no mapa de "
                    "serviço, a carga está na nota de porte, e é a ausência de uma "
                    "para a outra que o define.\n\n"
                    "Por troço, porque é assim que se resolve: um retorno vazio "
                    "repetido no mesmo sentido é uma carga de regresso por vender, não "
                    "um acaso.",
                    "Empty running is the most invisible cost in this industry. It all "
                    "shows up in the fuel and nowhere at all in the billing — so there "
                    "is no report where it is a line.\n\n"
                    "Nobody denies it and nobody knows how much it is. The number only "
                    "exists by joining trips to loads: the trip is on the duty roster, "
                    "the load is on the consignment note, and it is the absence of one "
                    "against the other that defines it.\n\n"
                    "By leg, because that is how it gets fixed: an empty return repeated "
                    "in the same direction is a backload nobody has sold, not bad luck."),
                "stat_tiles": [
                    tile(L("Quilómetros em vazio", "Kilometres run empty"), "km_vazio"),
                    tile(L("Gasóleo queimado sem carga", "Diesel burned with no load"),
                         "gasoleo_vazio", "eur"),
                    tile(L("O troço com mais vazio", "The leg with the most empty running"),
                         "troco_mais_vazio"),
                ],
                "sources": [F[0], F[1], F[4]],
                "executed_sql": SQL_VAZIO,
                "series_sql": SQL_SERIE_VAZIO,
            },
            {
                "severity": "sla_breach",
                "severity_level": "info",
                "agent_name": L("Serviço", "Service"),
                "title": L("Duas rotas falham a hora em mais de metade das viagens",
                           "Two routes miss the clock on more than half their trips"),
                "summary": L(
                    "A pontualidade média da operação é boa, e é por isso que estas duas "
                    "rotas nunca chegaram a uma reunião: a média tapa-as.\n\n"
                    "O que torna o número honesto é medir contra a tolerância "
                    "contratada de cada cliente e não contra uma hora fixa. O mesmo "
                    "atraso de quarenta minutos é indiferente numa carga de construção "
                    "e é uma penalização numa de frio.\n\n"
                    "Quando uma rota falha quase sempre, o problema não é o trânsito — "
                    "é o tempo padrão, que foi estimado uma vez e nunca mais foi "
                    "olhado.",
                    "The operation's average punctuality is good, and that is precisely "
                    "why these two routes never reached a meeting: the average hides "
                    "them.\n\n"
                    "What makes the number honest is measuring against each client's "
                    "contracted tolerance rather than a fixed hour. The same forty "
                    "minutes is irrelevant on a construction load and a penalty on a "
                    "chilled one.\n\n"
                    "When a route misses almost every time, the problem is not traffic — "
                    "it is the standard time, estimated once and never looked at again."),
                "stat_tiles": [
                    tile(L("Dentro do prazo do cliente", "Within the client's window"),
                         "pontualidade", "pct"),
                    tile(L("Portes fora de prazo", "Consignments outside the window"),
                         "portes_fora_sla"),
                    tile(L("A pior rota", "The worst route"), "pior_rota"),
                ],
                "sources": [F[0], F[4], F[5]],
                "executed_sql": SQL_SLA,
                "series_sql": SQL_SERIE_SLA,
            },
        ],
        "qas": [
            {
                "position": 0,
                "is_suggested": True,
                "question": L("Que viaturas custam mais por quilómetro do que rendem?",
                              "Which vehicles cost more per kilometre than they earn?"),
                "answer_markdown": L(
                    "**As mais velhas — e são as que ninguém questiona**, porque já não "
                    "têm prestação.\n\n"
                    "O custo por quilómetro soma quatro coisas que vivem em quatro "
                    "sistemas: gasóleo, horas de motorista, portagens e oficina, mais o "
                    "custo fixo da viatura. A receita vem da nota de porte. A conta é "
                    "trivial; o que não é trivial é ter as quatro parcelas no mesmo "
                    "sítio.\n\n"
                    "O quadro está ordenado pela contribuição em euros e não pela "
                    "percentagem: uma viatura que anda muito e ganha pouco por "
                    "quilómetro custa mais do que uma que anda pouco e perde em cada "
                    "um — e é a primeira que vale a pena resolver.",
                    "**The oldest ones — and they are the ones nobody questions**, "
                    "because they no longer have a lease.\n\n"
                    "Cost per kilometre adds four things that live in four systems: "
                    "diesel, driver hours, tolls and the workshop, plus the vehicle's "
                    "fixed cost. Revenue comes from the consignment note. The sum is "
                    "trivial; what is not trivial is having the four pieces in the same "
                    "place.\n\n"
                    "The table is ordered by contribution in euros, not by percentage: a "
                    "vehicle that runs a lot and earns little per kilometre costs more "
                    "than one that barely runs and loses on each — and it is the first "
                    "that is worth fixing."),
                "citations": [{"table": "fleet.vehicles"}, {"table": "ops.trips"},
                              {"table": "fleet.maintenance_jobs"}],
                "executed_sql": SQL_CUSTO_KM,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Custo médio por km", "Average cost per km"), "custo_km_medio", "eur"),
                    tile(L("Diferença entre as duas metades da frota",
                           "Gap between the two halves of the fleet"),
                         "diferenca_contribuicao", "eur"),
                    tile(L("A pior delas", "The worst of them"), "pior_viatura"),
                ],
            },
            {
                "position": 1,
                "is_suggested": True,
                "question": L("Quantos quilómetros andamos em vazio, e em que troços?",
                              "How many kilometres do we run empty, and on which legs?"),
                "answer_markdown": L(
                    "**Cerca de um quinto de tudo o que a frota anda.** Gasóleo, "
                    "motorista e portagens pagos; faturação zero.\n\n"
                    "Não há nenhum sistema onde esta linha exista, porque ela é definida "
                    "por uma ausência: uma viagem registada sem nenhuma carga associada. "
                    "A viagem está no mapa de serviço e a carga está na nota de porte; "
                    "é preciso ter os dois para ver o buraco.\n\n"
                    "Por troço, e ordenado pelo gasóleo queimado, porque é assim que se "
                    "age: um troço que volta vazio todas as semanas é uma carga de "
                    "regresso por vender, e tem nome e sentido.",
                    "**About a fifth of everything the fleet runs.** Diesel, driver and "
                    "tolls paid; nothing billed.\n\n"
                    "There is no system where this line exists, because it is defined by "
                    "an absence: a logged trip with no load attached to it. The trip is "
                    "on the duty roster and the load is on the consignment note; you need "
                    "both to see the hole.\n\n"
                    "By leg, ordered by diesel burned, because that is how it gets acted "
                    "on: a leg that comes back empty every week is a backload nobody has "
                    "sold, and it has a name and a direction."),
                "citations": [{"table": "ops.trips"}, {"table": "freight.shipments"},
                              {"table": "ops.routes"}],
                "executed_sql": SQL_VAZIO,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Quilómetros em vazio", "Kilometres run empty"), "km_vazio"),
                    tile(L("Gasóleo queimado sem carga", "Diesel burned with no load"),
                         "gasoleo_vazio", "eur"),
                    tile(L("Do total percorrido", "Of all distance run"), "km_vazio_pct", "pct"),
                ],
            },
            {
                "position": 2,
                "is_suggested": True,
                "question": L("Que rotas chegam fora do prazo combinado com o cliente?",
                              "Which routes arrive outside the window agreed with the client?"),
                "answer_markdown": L(
                    "**Duas, e falham quase sempre.** O resto da operação anda nos 6 a "
                    "8 por cento, que é ruído normal.\n\n"
                    "A média da empresa é boa — e é exactamente por isso que estas duas "
                    "nunca chegaram a uma reunião. Uma rota que falha 60% das vezes "
                    "desaparece numa média de 89%.\n\n"
                    "A medição é contra a tolerância contratada de cada cliente, não "
                    "contra uma hora fixa: quarenta minutos não é a mesma coisa numa "
                    "carga de cerâmica e numa de fruta.\n\n"
                    "Quando uma rota falha sistematicamente, a causa quase nunca é o "
                    "trânsito — é o tempo padrão, estimado uma vez e nunca revisto.",
                    "**Two, and they miss almost every time.** The rest of the operation "
                    "sits at 6 to 8 per cent, which is normal noise.\n\n"
                    "The company average is good — and that is exactly why these two "
                    "never reached a meeting. A route that misses 60% of the time "
                    "disappears inside an 89% average.\n\n"
                    "The measurement is against each client's contracted tolerance, not a "
                    "fixed hour: forty minutes is not the same thing on a load of tiles "
                    "and a load of fruit.\n\n"
                    "When a route misses systematically, the cause is almost never "
                    "traffic — it is the standard time, estimated once and never "
                    "revisited."),
                "citations": [{"table": "ops.trips"}, {"table": "ops.routes"},
                              {"table": "freight.clients"}],
                "executed_sql": SQL_SLA,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Dentro do prazo do cliente", "Within the client's window"),
                         "pontualidade", "pct"),
                    tile(L("Portes fora de prazo", "Consignments outside the window"),
                         "portes_fora_sla"),
                    tile(L("A pior rota", "The worst route"), "pior_rota"),
                ],
            },
            {
                "position": 3,
                "is_suggested": False,
                "question": L("Que clientes pagam melhor por quilómetro?",
                              "Which clients pay best per kilometre?"),
                "answer_markdown": L(
                    "**Por euro facturado a dividir pelos quilómetros que foi preciso "
                    "andar para o facturar** — que é diferente de quem factura mais.\n\n"
                    "Um cliente grande que obriga a atravessar o país por carga meia "
                    "vazia pode render menos por quilómetro do que um pequeno à porta do "
                    "armazém. A facturação total não diz isso; o euro por quilómetro "
                    "diz.\n\n"
                    "A coluna dos incidentes está ao lado de propósito: carga danificada "
                    "e falha de temperatura custam dinheiro que nunca aparece na tabela "
                    "de preços.",
                    "**By euro billed divided by the kilometres it took to bill it** — "
                    "which is not the same as who bills most.\n\n"
                    "A large client that makes you cross the country for a half-empty "
                    "load can pay less per kilometre than a small one at the depot gate. "
                    "Total billing does not say that; euro per kilometre does.\n\n"
                    "The incident column sits beside it deliberately: damaged goods and "
                    "temperature failures cost money that never shows up on the rate "
                    "card."),
                "citations": [{"table": "freight.clients"}, {"table": "freight.shipments"}],
                "executed_sql": SQL_CLIENTES,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Melhor cliente por km", "Best client per km"), "cliente_melhor_km"),
                    tile(L("Facturado no período", "Billed in the period"), "receita_total", "eur"),
                    tile(L("Incidentes de carga", "Load incidents"), "incidentes"),
                ],
            },
            {
                "position": 4,
                "is_suggested": False,
                "question": L("Quanto nos custou a oficina, e que viaturas a puxam?",
                              "What did the workshop cost us, and which vehicles drive it?"),
                "answer_markdown": L(
                    "**A factura da oficina é metade da história; os dias fora da "
                    "estrada são a outra metade** — e só a primeira tem um documento.\n\n"
                    "Um camião parado não deixa de ter leasing, seguro e imposto, e a "
                    "carga que ele não fez ou foi recusada ou foi subcontratada. Esse "
                    "custo não tem factura nenhuma, e por isso não entra em nenhuma "
                    "conta.\n\n"
                    "A separação entre avaria e preventiva é o que interessa: preventiva "
                    "a mais é caro, preventiva a menos é mais caro.",
                    "**The workshop invoice is half the story; the days off road are the "
                    "other half** — and only the first one has a document.\n\n"
                    "A truck standing still still has its lease, insurance and road tax, "
                    "and the load it did not run was either refused or subcontracted. "
                    "That cost has no invoice at all, and so it enters no account.\n\n"
                    "Splitting breakdown from preventive is what matters: too much "
                    "preventive is expensive, too little is more expensive."),
                "citations": [{"table": "fleet.maintenance_jobs"}, {"table": "fleet.vehicles"}],
                "executed_sql": SQL_OFICINA,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Oficina no período", "Workshop in the period"), "oficina_total", "eur"),
                    tile(L("Dias fora da estrada", "Days off road"), "dias_fora_estrada"),
                    tile(L("Avarias", "Breakdowns"), "avarias"),
                ],
            },
            {
                "position": 5,
                "is_suggested": False,
                "question": L("Que motoristas acumulam mais horas ao volante?",
                              "Which drivers are accumulating the most hours at the wheel?"),
                "answer_markdown": L(
                    "**Antes de ser um custo, é um risco de tacógrafo.** Os tempos de "
                    "condução são matéria de coima e de responsabilidade, e a escala é "
                    "feita por quem tem a carga à frente, não por quem tem o mapa de "
                    "horas.\n\n"
                    "A coluna do cumprimento do tempo padrão está ao lado para evitar a "
                    "leitura errada: quem acumula horas não é necessariamente quem "
                    "trabalha mais devagar — pode ser quem apanha sempre as rotas "
                    "longas.\n\n"
                    "Sai do cruzamento das viagens com o cadastro de motoristas.",
                    "**Before it is a cost, it is a tachograph risk.** Driving times are "
                    "a matter of fines and liability, and the roster is made by whoever "
                    "has the load in front of them, not by whoever has the hours "
                    "sheet.\n\n"
                    "The standard-time column sits beside it to head off the wrong "
                    "reading: whoever accumulates hours is not necessarily whoever works "
                    "slowest — it may be whoever always draws the long routes.\n\n"
                    "It comes from joining trips to the driver register."),
                "citations": [{"table": "fleet.drivers"}, {"table": "ops.trips"}],
                "executed_sql": SQL_MOTORISTAS,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Mais horas ao volante", "Most hours at the wheel"),
                         "motorista_mais_horas"),
                    tile(L("Viagens concluídas", "Trips completed"), "viagens"),
                    tile(L("Dentro do prazo do cliente", "Within the client's window"),
                         "pontualidade", "pct"),
                ],
            },
        ],
    }


def main() -> None:
    doc = json.loads(ALVO.read_text(encoding="utf-8"))
    outros = [
        d for d in doc["datasets"]
        if not (d["vertical"] == "transport" and d["locale"] in ("pt", "en"))
    ]
    doc["datasets"] = outros + [dataset("pt"), dataset("en")]
    ALVO.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"transport pt+en escritos em {ALVO.name}")


if __name__ == "__main__":
    main()
