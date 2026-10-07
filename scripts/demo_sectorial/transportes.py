# -*- coding: utf-8 -*-
"""Demonstração sectorial — Logística e Transportes, em castelhano.

Serve as transportadoras: a mesma demonstração para a Serlogic e para a
Lafões, porque as três perguntas que decidem o ano são as mesmas em
qualquer operação de carga.

Os dados vêm de `scripts/demo/seed_transport.sql` — sintéticos, gerados
por fórmula, de nenhum cliente real.

── Porque é que há três ligações e não uma ─────────────────────────

Uma ligação Postgres tem **um** esquema (`_safe_schema`, em
`src/connectors/postgresql.py`): ou se indica um, e só esse é
descoberto, ou se deixa vazio e vêm todos — incluindo os dos outros
sectores que vivem na mesma base `skydemo`. Um painel de transportes
que mostre `quality.scrap` na lista de tabelas perde a sala.

Daí três: Flota, Operaciones e Carga. É também a melhor imagem para o
Context Graph — três fontes que não se falam, que é exactamente a
situação do cliente.

── A consequência, e o que se faz com ela ──────────────────────────

As perguntas que valem mais atravessam os três esquemas: o custo está
em `ops`, a receita está em `freight`, e a idade da viatura está em
`fleet`. Nenhum agente apontado a uma ligação consegue fazer essa
junção.

Por isso a divisão é deliberada:

  * **os painéis** levam as junções, pré-calculadas na sementeira. São
    o que está no ecrã durante a reunião, e não podem falhar;
  * **os agentes** fazem perguntas que vivem dentro de um esquema. São
    o que corre ao vivo à frente do cliente, e por isso têm de
    funcionar mesmo — não "quase".

Prometer uma junção ao vivo que o produto hoje não faz seria ganhar a
demonstração e perder a implementação.
"""

from __future__ import annotations

from scripts.demo_sectorial.formato import eur, euro2, n, pct
from scripts.demo_sectorial.pecas import (
    AMBAR,
    AZUL,
    VERDE,
    Agente,
    Pagina,
    Sector,
    grafico,
    kpi,
    paragrafos,
    tabela,
    texto,
)

# ── blocos de SQL reutilizados ──────────────────────────────────────
#
# O custo completo de uma viatura: gasóleo, motorista, portagens,
# oficina e o custo fixo. Cada parcela vive num sistema diferente na
# vida real, e é a soma que ninguém tem.

_FROTA = """WITH custo AS (
    SELECT t.vehicle_id, SUM(t.km_run) AS km,
           SUM(t.fuel_litres * 1.62 + t.driver_hours * d.cost_per_hour
               + r.toll_cost) AS variavel
    FROM ops.trips t
    JOIN fleet.drivers d ON d.id = t.driver_id
    JOIN ops.routes r ON r.id = t.route_id
    WHERE t.status = 'completed'
    GROUP BY t.vehicle_id
), oficina AS (
    SELECT vehicle_id, SUM(cost) AS taller, SUM(days_off_road) AS dias
    FROM fleet.maintenance_jobs GROUP BY vehicle_id
), receita AS (
    SELECT t.vehicle_id, SUM(s.revenue) AS ingreso
    FROM ops.trips t JOIN freight.shipments s ON s.trip_id = t.id
    GROUP BY t.vehicle_id
), frota AS (
    SELECT v.plate,
           EXTRACT(YEAR FROM v.acquired_on)::INT AS anio,
           c.km,
           c.variavel + COALESCE(o.taller, 0) + v.fixed_cost_month * 12 AS coste,
           COALESCE(i.ingreso, 0) AS ingreso
    FROM fleet.vehicles v
    JOIN custo c ON c.vehicle_id = v.id
    LEFT JOIN oficina o ON o.vehicle_id = v.id
    LEFT JOIN receita i ON i.vehicle_id = v.id
)"""

_VAZIO = (
    "FROM ops.trips t LEFT JOIN freight.shipments s ON s.trip_id = t.id "
    "WHERE t.status = 'completed'"
)
_PLAZO = (
    "FROM ops.trips t JOIN freight.shipments s ON s.trip_id = t.id "
    "JOIN freight.clients c ON c.id = s.client_id WHERE t.status = 'completed'"
)
_FUERA = "t.arrived_at > t.planned_arrival + (c.sla_minutes * INTERVAL '1 minute')"


SECTOR = Sector(
    chave="transportes",
    nome_do_projecto="Logística y Transporte",
    descricao=(
        "Demostración sectorial: rentabilidad de flota, vacío de retorno y "
        "cumplimiento de plazos sobre 12 meses de operación."
    ),
    ligacoes={
        "flota": (
            "Flota",
            "fleet",
            "Vehículos, conductores y taller. El sistema que sabe lo que cuesta "
            "tener el camión, y no lo que gana.",
        ),
        "operaciones": (
            "Operaciones",
            "ops",
            "Rutas y viajes: kilómetros, gasóleo, horas y hora de llegada. El "
            "sistema que sabe lo que el camión hizo.",
        ),
        "carga": (
            "Carga",
            "freight",
            "Clientes y portes: peso, palés, importe e incidencias. El sistema "
            "que sabe lo que se facturó.",
        ),
    },
    paginas=[
        # ─────────────────────────────────────────────────────────────
        Pagina(
            nome="Rentabilidad de flota",
            descricao=(
                "Lo que cada vehículo aporta después de pagar lo que él mismo "
                "consume. No es beneficio de la empresa: la estructura no está aquí."
            ),
            icone="truck",
            cor="#F5A623",
            widgets=[
                kpi(
                    "Coste medio por km",
                    "kpi1",
                    "operaciones",
                    _FROTA + " SELECT ROUND(SUM(coste) / NULLIF(SUM(km), 0), 2) AS v FROM frota",
                    legenda="Gasóleo, conductor, peajes, taller y coste fijo",
                    formato="currency",
                ),
                kpi(
                    "Ingreso medio por km",
                    "kpi2",
                    "carga",
                    _FROTA + " SELECT ROUND(SUM(ingreso) / NULLIF(SUM(km), 0), 2) AS v FROM frota",
                    legenda="Lo facturado dividido por todo lo rodado",
                    formato="currency",
                ),
                kpi(
                    "Vehículos que no se pagan",
                    "kpi3",
                    "flota",
                    _FROTA + " SELECT COUNT(*) AS v FROM frota WHERE ingreso < coste",
                    legenda="Ingresan menos de lo que cuestan",
                ),
                kpi(
                    "Diferencia entre las dos mitades",
                    "kpi4",
                    "flota",
                    _FROTA
                    + """ SELECT ROUND(
                        (SELECT AVG(ingreso - coste) FROM frota
                          WHERE ingreso - coste > (SELECT AVG(ingreso - coste) FROM frota))
                      - (SELECT AVG(ingreso - coste) FROM frota
                          WHERE ingreso - coste <= (SELECT AVG(ingreso - coste) FROM frota))
                    ) AS v""",
                    legenda="Lo que la media flota baja aporta de menos, al año",
                    formato="currency",
                ),
                grafico(
                    "Aportación por vehículo",
                    "esq1",
                    "flota",
                    _FROTA
                    + """ SELECT plate AS matricula,
                                        ROUND(ingreso - coste) AS aportacion
                                 FROM frota ORDER BY aportacion""",
                    variante="bar",
                    x="matricula",
                    y="aportacion",
                ),
                tabela(
                    "Coste e ingreso por kilómetro",
                    "dir1",
                    "flota",
                    _FROTA
                    + """ SELECT plate AS "Matrícula",
                                        anio AS "Año",
                                        ROUND(km) AS "Km",
                                        ROUND(coste / NULLIF(km, 0), 2) AS "Coste/km",
                                        ROUND(ingreso / NULLIF(km, 0), 2) AS "Ingreso/km",
                                        ROUND(ingreso - coste) AS "Aportación"
                                 FROM frota ORDER BY ingreso - coste""",
                ),
                texto(
                    "Las dos mitades",
                    "terco1a",
                    "flota",
                    _FROTA
                    + """ SELECT COUNT(*) FILTER (WHERE ingreso < coste) AS malos,
                                 COUNT(*) AS total,
                                 ROUND(SUM(coste - ingreso) FILTER (WHERE ingreso < coste))
                                   AS fuga
                          FROM frota""",
                    corpo=lambda r: paragrafos(
                        "LA MITAD QUE NO SE PAGA",
                        f"{r[0]['malos']} de {r[0]['total']} vehículos ingresan menos de lo "
                        f"que cuestan. Entre todos se llevan {eur(r[0]['fuga'])} al año.",
                        "Nadie los defiende en una reunión de costes porque este número no "
                        "existe en ningún sistema: el coste está en operaciones y el ingreso "
                        "en facturación.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "Qué incluye el coste",
                    "terco1b",
                    "operaciones",
                    _FROTA
                    + """ SELECT ROUND(SUM(coste)) AS coste,
                                 ROUND(SUM(ingreso)) AS ingreso
                          FROM frota""",
                    corpo=lambda r: paragrafos(
                        "QUÉ ESTÁ CONTADO AQUÍ",
                        "Gasóleo, horas de conductor, peajes, taller y coste fijo mensual "
                        "— leasing, seguro e impuesto.",
                        f"Coste {eur(r[0]['coste'])} frente a {eur(r[0]['ingreso'])} "
                        "facturados. No es el beneficio de la empresa: la estructura no "
                        "está aquí.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "El que mejor trabaja",
                    "terco1c",
                    "flota",
                    _FROTA
                    + """ SELECT plate, anio, ROUND(ingreso - coste) AS aporta,
                                 ROUND(ingreso / NULLIF(km, 0), 2) AS por_km
                          FROM frota ORDER BY ingreso - coste DESC LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "EL MEJOR DE LA FLOTA",
                        f"{r[0]['plate']} ({r[0]['anio']}) aporta {eur(r[0]['aporta'])} "
                        f"al año, a {euro2(r[0]['por_km'])} por kilómetro facturado.",
                        "Es el patrón que se busca al reponer: qué clase de vehículo, "
                        "en qué rutas.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Margen de viaje, mes a mes",
                    "esq2",
                    "operaciones",
                    """SELECT TO_CHAR(DATE_TRUNC('month', t.departed_at), 'YYYY-MM') AS mes,
                              ROUND(COALESCE(SUM(s.revenue), 0)
                                    - SUM(t.fuel_litres * 1.62
                                          + t.driver_hours * d.cost_per_hour
                                          + r.toll_cost)) AS margen
                       FROM ops.trips t
                       JOIN fleet.drivers d ON d.id = t.driver_id
                       JOIN ops.routes r ON r.id = t.route_id
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'
                       GROUP BY 1 ORDER BY 1""",
                    variante="area",
                    x="mes",
                    y="margen",
                ),
                grafico(
                    "Coste por km, por clase de vehículo",
                    "dir2",
                    "flota",
                    """SELECT v.class AS clase,
                              ROUND(SUM(t.fuel_litres * 1.62
                                        + t.driver_hours * d.cost_per_hour)
                                    / NULLIF(SUM(t.km_run), 0), 2) AS eur_km
                       FROM ops.trips t
                       JOIN fleet.vehicles v ON v.id = t.vehicle_id
                       JOIN fleet.drivers d ON d.id = t.driver_id
                       WHERE t.status = 'completed'
                       GROUP BY v.class ORDER BY eur_km DESC""",
                    variante="column",
                    x="clase",
                    y="eur_km",
                ),
                tabela(
                    "Kilómetros y consumo por vehículo",
                    "larga3",
                    "operaciones",
                    """SELECT v.plate AS "Matrícula",
                              v.class AS "Clase",
                              COUNT(*) AS "Viajes",
                              SUM(t.km_run) AS "Km",
                              ROUND(AVG(t.km_run)) AS "Km por viaje",
                              ROUND(100.0 * SUM(t.fuel_litres)
                                    / NULLIF(SUM(t.km_run), 0), 1) AS "Litros/100 km",
                              ROUND(SUM(t.driver_hours)) AS "Horas de conductor"
                       FROM ops.trips t
                       JOIN fleet.vehicles v ON v.id = t.vehicle_id
                       WHERE t.status = 'completed'
                       GROUP BY v.id, v.plate, v.class
                       ORDER BY 4 DESC""",
                ),
            ],
        ),
        # ─────────────────────────────────────────────────────────────
        Pagina(
            nome="Vacío de retorno",
            descricao=(
                "Los kilómetros que se pagan y no se facturan. No hay ningún "
                "sistema donde esta línea exista: se define por una ausencia."
            ),
            icone="route",
            cor="#E8743B",
            widgets=[
                kpi(
                    "Kilómetros en vacío",
                    "kpi1",
                    "operaciones",
                    f"SELECT COALESCE(SUM(t.km_run), 0) AS v {_VAZIO} AND s.id IS NULL",
                    legenda="Viajes sin ninguna carga asociada",
                ),
                kpi(
                    "Del total rodado",
                    "kpi2",
                    "operaciones",
                    "SELECT ROUND(100.0 * SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END)"
                    f" / NULLIF(SUM(t.km_run), 0), 1) AS v {_VAZIO}",
                    legenda="Uno de cada cinco kilómetros",
                    formato="percent",
                ),
                kpi(
                    "Gasóleo quemado sin carga",
                    "kpi3",
                    "operaciones",
                    "SELECT COALESCE(ROUND(SUM(t.fuel_litres * 1.62)), 0) AS v "
                    f"{_VAZIO} AND s.id IS NULL",
                    legenda="A 1,62 €/litro",
                    formato="currency",
                ),
                kpi(
                    "El trayecto con más vacío",
                    "kpi4",
                    "operaciones",
                    "SELECT r.origin || ' - ' || r.destination AS v FROM ops.trips t "
                    "JOIN ops.routes r ON r.id = t.route_id "
                    "LEFT JOIN freight.shipments s ON s.trip_id = t.id "
                    "WHERE t.status = 'completed' AND s.id IS NULL "
                    "GROUP BY r.id, r.origin, r.destination "
                    "ORDER BY SUM(t.fuel_litres) DESC LIMIT 1",
                    legenda="Un retorno vacío repetido es un retorno sin vender",
                ),
                tabela(
                    "Vacío por trayecto",
                    "larga1",
                    "operaciones",
                    """SELECT r.origin || ' - ' || r.destination AS "Trayecto",
                              r.distance_km AS "Km",
                              COUNT(*) AS "Viajes",
                              COUNT(*) FILTER (WHERE s.id IS NULL) AS "En vacío",
                              SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END) AS "Km en vacío",
                              ROUND(SUM(CASE WHEN s.id IS NULL THEN t.fuel_litres * 1.62 ELSE 0 END)) AS "Gasóleo (€)"
                       FROM ops.trips t
                       JOIN ops.routes r ON r.id = t.route_id
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'
                       GROUP BY r.id, r.origin, r.destination, r.distance_km
                       HAVING COUNT(*) FILTER (WHERE s.id IS NULL) > 0
                       ORDER BY 6 DESC""",
                ),
                grafico(
                    "Porcentaje en vacío, mes a mes",
                    "larga2",
                    "operaciones",
                    """SELECT TO_CHAR(DATE_TRUNC('month', t.departed_at), 'YYYY-MM') AS mes,
                              ROUND(100.0 * SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END)
                                    / NULLIF(SUM(t.km_run), 0), 1) AS pct
                       FROM ops.trips t
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'
                       GROUP BY 1 ORDER BY 1""",
                    variante="line",
                    x="mes",
                    y="pct",
                ),
                texto(
                    "Por qué nadie lo ve",
                    "terco1a",
                    "operaciones",
                    """SELECT COUNT(*) FILTER (WHERE s.id IS NULL) AS vacios,
                              COUNT(*) AS viajes,
                              ROUND(SUM(CASE WHEN s.id IS NULL
                                             THEN t.fuel_litres * 1.62 ELSE 0 END)) AS gasoleo
                       FROM ops.trips t
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'""",
                    corpo=lambda r: paragrafos(
                        "UNA LÍNEA QUE NO EXISTE",
                        f"{n(r[0]['vacios'])} de {n(r[0]['viajes'])} viajes vuelven sin "
                        f"carga. {eur(r[0]['gasoleo'])} de gasóleo quemado sin facturar "
                        "nada.",
                        "Esta línea no está en ningún sistema suyo: se define por una "
                        "AUSENCIA — un viaje al que no corresponde ningún porte. Por eso "
                        "no aparece en ninguna cuenta.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "Lo que valdría llenarlos",
                    "terco1b",
                    "carga",
                    """WITH lleno AS (
                           SELECT SUM(s.revenue) / NULLIF(SUM(t.km_run), 0) AS eur_km
                           FROM freight.shipments s
                           JOIN ops.trips t ON t.id = s.trip_id
                       ), vacio AS (
                           SELECT SUM(t.km_run) AS km
                           FROM ops.trips t
                           LEFT JOIN freight.shipments s ON s.trip_id = t.id
                           WHERE t.status = 'completed' AND s.id IS NULL
                       )
                       SELECT ROUND(vacio.km * lleno.eur_km) AS potencial,
                              ROUND(lleno.eur_km, 2) AS eur_km
                       FROM lleno, vacio""",
                    corpo=lambda r: paragrafos(
                        "EL TECHO DE ESTA PÁGINA",
                        f"A {euro2(r[0]['eur_km'])} por kilómetro facturado, esos "
                        f"kilómetros en vacío valdrían {eur(r[0]['potencial'])}.",
                        "No es un objetivo — nadie llena todos los retornos. Es el tamaño "
                        "del problema, para saber cuánto merece la pena pelearlo.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Dónde empezar",
                    "terco1c",
                    "operaciones",
                    """SELECT r.origin || ' - ' || r.destination AS trayecto,
                              COUNT(*) FILTER (WHERE s.id IS NULL) AS vacios,
                              ROUND(SUM(CASE WHEN s.id IS NULL
                                             THEN t.fuel_litres * 1.62 ELSE 0 END)) AS gasoleo
                       FROM ops.trips t
                       JOIN ops.routes r ON r.id = t.route_id
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'
                       GROUP BY r.id, r.origin, r.destination
                       ORDER BY 3 DESC LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "POR DÓNDE SE EMPIEZA",
                        f"{r[0]['trayecto']}: {n(r[0]['vacios'])} retornos vacíos, "
                        f"{eur(r[0]['gasoleo'])} de gasóleo.",
                        "Un retorno vacío que se repite siempre en el mismo trayecto no es "
                        "mala suerte — es un cliente que falta en ese sentido.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Km en vacío por trayecto",
                    # Fila 3: nesta página a 1 e a 2 já são `larga1` e
                    # `larga2`, e as metades colidiriam com elas.
                    "esq3",
                    "operaciones",
                    """SELECT r.origin || ' - ' || r.destination AS trayecto,
                              SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END) AS km
                       FROM ops.trips t
                       JOIN ops.routes r ON r.id = t.route_id
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'
                       GROUP BY r.id, r.origin, r.destination
                       HAVING SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END) > 0
                       ORDER BY km DESC""",
                    variante="bar",
                    x="trayecto",
                    y="km",
                ),
                grafico(
                    "Reparto de los kilómetros",
                    "dir3",
                    "operaciones",
                    """SELECT CASE WHEN s.id IS NULL THEN 'En vacío' ELSE 'Con carga' END
                                AS estado,
                              SUM(t.km_run) AS km
                       FROM ops.trips t
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'
                       GROUP BY 1 ORDER BY km DESC""",
                    variante="pie",
                    x="estado",
                    y="km",
                ),
                tabela(
                    "Vacío por vehículo",
                    "larga4",
                    "flota",
                    """SELECT v.plate AS "Matrícula",
                              v.class AS "Clase",
                              COUNT(*) AS "Viajes",
                              COUNT(*) FILTER (WHERE s.id IS NULL) AS "En vacío",
                              ROUND(100.0 * COUNT(*) FILTER (WHERE s.id IS NULL)
                                    / COUNT(*), 1) AS "% en vacío",
                              ROUND(SUM(CASE WHEN s.id IS NULL
                                             THEN t.fuel_litres * 1.62 ELSE 0 END))
                                AS "Gasóleo en vacío (€)"
                       FROM ops.trips t
                       JOIN fleet.vehicles v ON v.id = t.vehicle_id
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'
                       GROUP BY v.id, v.plate, v.class
                       ORDER BY 5 DESC""",
                ),
            ],
        ),
        # ─────────────────────────────────────────────────────────────
        Pagina(
            nome="Plazos y servicio",
            descricao=(
                "Medido contra la tolerancia contratada de cada cliente, no "
                "contra una hora fija. Cuarenta minutos no es lo mismo en "
                "cerámica que en fruta."
            ),
            icone="clock",
            cor="#4A90D9",
            widgets=[
                kpi(
                    "Dentro del plazo del cliente",
                    "kpi1",
                    "carga",
                    "SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE NOT (" + _FUERA + "))"
                    f" / COUNT(*), 1) AS v {_PLAZO}",
                    legenda="La media tapa las dos rutas que fallan",
                    formato="percent",
                ),
                kpi(
                    "Portes fuera de plazo",
                    "kpi2",
                    "carga",
                    f"SELECT COUNT(*) AS v {_PLAZO} AND {_FUERA}",
                    legenda="Cada uno es una llamada del cliente",
                ),
                kpi(
                    "La peor ruta",
                    "kpi3",
                    "operaciones",
                    # Escrita por extenso, sem colar os blocos do topo. A
                    # primeira versão reutilizava o `_PLAZO` e falava de
                    # `r` sem ter feito o JOIN a `ops.routes`. O Postgres
                    # disse "missing FROM-clause entry for table r" — mas
                    # só quando a consulta chegou a correr, que é o
                    # argumento todo para o ensaio existir.
                    """SELECT r.origin || ' - ' || r.destination AS v
                       FROM ops.trips t
                       JOIN ops.routes r ON r.id = t.route_id
                       JOIN freight.shipments s ON s.trip_id = t.id
                       JOIN freight.clients c ON c.id = s.client_id
                       WHERE t.status = 'completed'
                       GROUP BY r.id, r.origin, r.destination
                       ORDER BY 100.0 * COUNT(*) FILTER (
                           WHERE t.arrived_at > t.planned_arrival
                                 + (c.sla_minutes * INTERVAL '1 minute')
                       ) / COUNT(*) DESC
                       LIMIT 1""",
                    legenda="Falla en dos de cada tres viajes",
                ),
                kpi(
                    "Incidencias de carga",
                    "kpi4",
                    "carga",
                    "SELECT COUNT(*) AS v FROM freight.shipments WHERE incident IS NOT NULL",
                    legenda="Daños, temperatura y documentación",
                ),
                grafico(
                    "Puntualidad mes a mes",
                    "esq1",
                    "carga",
                    "SELECT TO_CHAR(DATE_TRUNC('month', t.departed_at), 'YYYY-MM') AS mes, "
                    "ROUND(100.0 * COUNT(*) FILTER (WHERE NOT (" + _FUERA + "))"
                    f" / COUNT(*), 1) AS pct {_PLAZO} GROUP BY 1 ORDER BY 1",
                    variante="line",
                    x="mes",
                    y="pct",
                ),
                tabela(
                    "Cumplimiento por ruta",
                    "dir1",
                    "operaciones",
                    "SELECT r.origin || ' - ' || r.destination AS \"Ruta\", "
                    'r.distance_km AS "Km", r.standard_minutes AS "Estándar (min)", '
                    'COUNT(*) AS "Viajes", '
                    "ROUND(100.0 * COUNT(*) FILTER (WHERE " + _FUERA + ") / COUNT(*), 1) "
                    'AS "Fuera de plazo (%)", '
                    "ROUND(AVG(EXTRACT(EPOCH FROM (t.arrived_at - t.planned_arrival)) / 60)) "
                    'AS "Retraso medio (min)" '
                    "FROM ops.trips t "
                    "JOIN ops.routes r ON r.id = t.route_id "
                    "JOIN freight.shipments s ON s.trip_id = t.id "
                    "JOIN freight.clients c ON c.id = s.client_id "
                    "WHERE t.status = 'completed' "
                    "GROUP BY r.id, r.origin, r.destination, r.distance_km, r.standard_minutes "
                    "ORDER BY 5 DESC",
                ),
                texto(
                    "La media no manda a ningún sitio",
                    "terco1a",
                    "carga",
                    # A frase fala da DISPERSÃO, por isso a consulta tem de
                    # a medir. A primeira versão dizia «duas rutas falham
                    # em dois de cada três viajes» com o número escrito à
                    # mão — a asserção que este ficheiro inteiro existe
                    # para não fazer, e que o cartão ao lado pode
                    # contradizer no mesmo ecrã.
                    """WITH por_ruta AS (
                           SELECT r.id,
                                  100.0 * COUNT(*) FILTER (
                                      WHERE t.arrived_at > t.planned_arrival
                                            + (c.sla_minutes * INTERVAL '1 minute')
                                  ) / COUNT(*) AS pct
                           FROM ops.trips t
                           JOIN ops.routes r ON r.id = t.route_id
                           JOIN freight.shipments s ON s.trip_id = t.id
                           JOIN freight.clients c ON c.id = s.client_id
                           WHERE t.status = 'completed'
                           GROUP BY r.id
                       )
                       SELECT ROUND((SELECT AVG(pct) FROM por_ruta), 1) AS media,
                              ROUND((SELECT MAX(pct) FROM por_ruta), 1) AS peor,
                              ROUND((SELECT MIN(pct) FROM por_ruta), 1) AS mejor,
                              (SELECT COUNT(*) FROM por_ruta) AS rutas,
                              (SELECT COUNT(*) FROM por_ruta
                                 WHERE pct > 2 * (SELECT AVG(pct) FROM por_ruta))
                                AS malas""",
                    corpo=lambda r: paragrafos(
                        "LA MEDIA ESCONDE EL PROBLEMA",
                        f"De media, {pct(r[0]['media'])} de los portes llegan fuera del "
                        f"plazo del cliente, repartido entre {r[0]['rutas']} rutas.",
                        f"Pero no está repartido: la peor falla en {pct(r[0]['peor'])} de "
                        f"los viajes y la mejor en {pct(r[0]['mejor'])}. "
                        f"{r[0]['malas']} rutas están por encima del doble de la media — "
                        "y la media es justo el número que no le dice cuáles.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "Medido contra el contrato",
                    "terco1b",
                    "carga",
                    """SELECT MIN(sla_minutes) AS min_sla,
                              MAX(sla_minutes) AS max_sla,
                              COUNT(*) AS clientes
                       FROM freight.clients""",
                    corpo=lambda r: paragrafos(
                        "CONTRA SU PLAZO, NO CONTRA UNA HORA",
                        f"Los {r[0]['clientes']} clientes tienen tolerancias distintas: "
                        f"de {r[0]['min_sla']} a {r[0]['max_sla']} minutos.",
                        "Cuarenta minutos no es lo mismo en cerámica que en fruta. Medir "
                        "todo contra una hora fija da un cumplimiento que no se parece "
                        "al que el cliente siente.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Lo que el retraso cuesta",
                    "terco1c",
                    "carga",
                    "SELECT COUNT(*) FILTER (WHERE incident IS NOT NULL) AS incidencias,"
                    " COUNT(*) AS portes,"
                    " ROUND(SUM(revenue) FILTER (WHERE incident IS NOT NULL)) AS en_juego"
                    " FROM freight.shipments",
                    corpo=lambda r: paragrafos(
                        "LO QUE ESTÁ EN JUEGO",
                        f"{n(r[0]['incidencias'])} incidencias de carga sobre "
                        f"{n(r[0]['portes'])} portes, en envíos que facturan "
                        f"{eur(r[0]['en_juego'])}.",
                        "Un retraso no cuesta una penalización: cuesta la siguiente "
                        "licitación. Y eso no aparece en ninguna factura.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Retraso medio por cliente",
                    "esq2",
                    "carga",
                    """SELECT c.name AS cliente,
                              ROUND(AVG(EXTRACT(EPOCH FROM
                                    (t.arrived_at - t.planned_arrival)) / 60)) AS minutos
                       FROM ops.trips t
                       JOIN freight.shipments s ON s.trip_id = t.id
                       JOIN freight.clients c ON c.id = s.client_id
                       WHERE t.status = 'completed'
                       GROUP BY c.id, c.name ORDER BY minutos DESC""",
                    variante="bar",
                    x="cliente",
                    y="minutos",
                ),
                grafico(
                    "Portes fuera de plazo, mes a mes",
                    "dir2",
                    "carga",
                    "SELECT TO_CHAR(DATE_TRUNC('month', t.departed_at), 'YYYY-MM') AS mes,"
                    " COUNT(*) FILTER (WHERE " + _FUERA + ") AS fuera"
                    f" {_PLAZO} GROUP BY 1 ORDER BY 1",
                    variante="column",
                    x="mes",
                    y="fuera",
                ),
                tabela(
                    "Plazo por cliente",
                    "larga3",
                    "carga",
                    "SELECT c.name AS \"Cliente\","
                    ' c.sector AS "Sector",'
                    ' c.sla_minutes AS "Tolerancia (min)",'
                    ' COUNT(*) AS "Portes",'
                    " ROUND(100.0 * COUNT(*) FILTER (WHERE " + _FUERA + ")"
                    ' / COUNT(*), 1) AS "Fuera de plazo (%)",'
                    " ROUND(SUM(s.revenue)) AS \"Facturado (€)\""
                    f" {_PLAZO}"
                    " GROUP BY c.id, c.name, c.sector, c.sla_minutes"
                    " ORDER BY 5 DESC",
                ),
            ],
        ),
        # ─────────────────────────────────────────────────────────────
        Pagina(
            nome="Clientes y taller",
            descricao=(
                "Quién paga mejor por kilómetro — que no es quien más factura — "
                "y lo que el taller se llevó, con los días parados al lado."
            ),
            icone="users",
            cor="#7B61FF",
            widgets=[
                kpi(
                    "Mejor cliente por km",
                    "kpi1",
                    "carga",
                    "SELECT c.name AS v FROM freight.shipments s "
                    "JOIN ops.trips t ON t.id = s.trip_id "
                    "JOIN freight.clients c ON c.id = s.client_id "
                    "GROUP BY c.id, c.name "
                    "ORDER BY SUM(s.revenue) / NULLIF(SUM(t.km_run), 0) DESC LIMIT 1",
                    legenda="Facturación partida por kilómetros rodados",
                ),
                kpi(
                    "Facturado en el periodo",
                    "kpi2",
                    "carga",
                    "SELECT COALESCE(ROUND(SUM(revenue)), 0) AS v FROM freight.shipments",
                    legenda="12 meses de portes",
                    formato="currency",
                ),
                kpi(
                    "Taller en el periodo",
                    "kpi3",
                    "flota",
                    "SELECT COALESCE(ROUND(SUM(cost)), 0) AS v FROM fleet.maintenance_jobs",
                    legenda="Avería, preventivo y neumáticos",
                    formato="currency",
                ),
                kpi(
                    "Días fuera de la carretera",
                    "kpi4",
                    "flota",
                    "SELECT COALESCE(SUM(days_off_road), 0) AS v FROM fleet.maintenance_jobs",
                    legenda="Este coste no tiene factura, y por eso no entra en ninguna cuenta",
                ),
                grafico(
                    "Ingreso por kilómetro, por cliente",
                    "esq1",
                    "carga",
                    "SELECT c.name AS cliente, "
                    "ROUND(SUM(s.revenue) / NULLIF(SUM(t.km_run), 0), 2) AS eur_km "
                    "FROM freight.shipments s JOIN ops.trips t ON t.id = s.trip_id "
                    "JOIN freight.clients c ON c.id = s.client_id "
                    "GROUP BY c.id, c.name ORDER BY eur_km DESC",
                    variante="bar",
                    x="cliente",
                    y="eur_km",
                ),
                tabela(
                    "Taller por vehículo",
                    "dir1",
                    "flota",
                    'SELECT v.plate AS "Matrícula", '
                    'EXTRACT(YEAR FROM v.acquired_on)::INT AS "Año", '
                    "COUNT(*) FILTER (WHERE m.kind = 'avaria') AS \"Averías\", "
                    "COUNT(*) FILTER (WHERE m.kind = 'preventiva') AS \"Preventivo\", "
                    'ROUND(SUM(m.cost)) AS "Coste (€)", '
                    'SUM(m.days_off_road) AS "Días parado" '
                    "FROM fleet.vehicles v JOIN fleet.maintenance_jobs m ON m.vehicle_id = v.id "
                    "GROUP BY v.id, v.plate, v.acquired_on ORDER BY 5 DESC",
                ),
                texto(
                    "Quién factura y quién paga",
                    "terco1a",
                    "carga",
                    """WITH porkm AS (
                           SELECT c.name,
                                  SUM(s.revenue) AS factura,
                                  SUM(s.revenue) / NULLIF(SUM(t.km_run), 0) AS eur_km
                           FROM freight.shipments s
                           JOIN ops.trips t ON t.id = s.trip_id
                           JOIN freight.clients c ON c.id = s.client_id
                           GROUP BY c.id, c.name
                       )
                       SELECT (SELECT name FROM porkm ORDER BY factura DESC LIMIT 1)
                                AS mas_factura,
                              (SELECT name FROM porkm ORDER BY eur_km DESC LIMIT 1)
                                AS mejor_km,
                              (SELECT ROUND(eur_km, 2) FROM porkm
                                 ORDER BY eur_km DESC LIMIT 1) AS mejor_valor,
                              (SELECT ROUND(eur_km, 2) FROM porkm
                                 ORDER BY eur_km LIMIT 1) AS peor_valor""",
                    corpo=lambda r: paragrafos(
                        "NO SON EL MISMO CLIENTE",
                        f"El que más factura es {r[0]['mas_factura']}. El que mejor paga "
                        f"por kilómetro es {r[0]['mejor_km']}, a "
                        f"{euro2(r[0]['mejor_valor'])} frente a "
                        f"{euro2(r[0]['peor_valor'])} del último.",
                        "El ranking de facturación es el que todo el mundo mira, y es el "
                        "que menos dice: facturar mucho rodando mucho no deja nada.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "El coste sin factura",
                    "terco1b",
                    "flota",
                    """SELECT SUM(days_off_road) AS dias,
                              ROUND(SUM(cost)) AS coste,
                              COUNT(*) FILTER (WHERE kind = 'avaria') AS averias
                       FROM fleet.maintenance_jobs""",
                    corpo=lambda r: paragrafos(
                        "LOS DÍAS PARADOS",
                        f"{n(r[0]['dias'])} días fuera de la carretera y "
                        f"{eur(r[0]['coste'])} de taller, con {n(r[0]['averias'])} "
                        "averías.",
                        "El taller tiene factura; los días parados no. Un camión quieto "
                        "sigue pagando leasing y seguro, y ese coste no entra en ninguna "
                        "cuenta porque nadie lo emite.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Preventivo contra avería",
                    "terco1c",
                    "flota",
                    """SELECT ROUND(AVG(cost) FILTER (WHERE kind = 'preventiva')) AS prev,
                              ROUND(AVG(cost) FILTER (WHERE kind = 'avaria')) AS aver,
                              ROUND(AVG(days_off_road) FILTER (WHERE kind = 'avaria'), 1)
                                AS dias_aver
                       FROM fleet.maintenance_jobs""",
                    corpo=lambda r: paragrafos(
                        "LO QUE CUESTA ESPERAR",
                        f"Una preventiva cuesta {eur(r[0]['prev'])} de media. Una avería, "
                        f"{eur(r[0]['aver'])} y {r[0]['dias_aver']} días parado.",
                        "La diferencia es el argumento del mantenimiento planificado — y "
                        "se puede calcular por vehículo, no por intuición.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Taller mes a mes, por tipo",
                    "esq2",
                    "flota",
                    """SELECT TO_CHAR(DATE_TRUNC('month', done_on), 'YYYY-MM') AS mes,
                              ROUND(SUM(cost)) AS coste
                       FROM fleet.maintenance_jobs
                       GROUP BY 1 ORDER BY 1""",
                    variante="line",
                    x="mes",
                    y="coste",
                ),
                grafico(
                    "Reparto del gasto de taller",
                    "dir2",
                    "flota",
                    """SELECT kind AS tipo, ROUND(SUM(cost)) AS coste
                       FROM fleet.maintenance_jobs
                       GROUP BY kind ORDER BY coste DESC""",
                    variante="pie",
                    x="tipo",
                    y="coste",
                ),
                tabela(
                    "Clientes: facturación y kilómetros",
                    "larga3",
                    "carga",
                    """SELECT c.name AS "Cliente",
                              c.sector AS "Sector",
                              COUNT(*) AS "Portes",
                              SUM(s.pallets) AS "Palés",
                              SUM(t.km_run) AS "Km",
                              ROUND(SUM(s.revenue)) AS "Facturado (€)",
                              ROUND(SUM(s.revenue) / NULLIF(SUM(t.km_run), 0), 2)
                                AS "€/km"
                       FROM freight.shipments s
                       JOIN ops.trips t ON t.id = s.trip_id
                       JOIN freight.clients c ON c.id = s.client_id
                       GROUP BY c.id, c.name, c.sector
                       ORDER BY 7 DESC""",
                ),
            ],
        ),
    ],
    # ── os agentes ──────────────────────────────────────────────────
    #
    # Cada um vive dentro de UM esquema, pela razão explicada no topo.
    # Correm ao vivo à frente do cliente: têm de funcionar, não "quase".
    agentes=[
        Agente(
            nome="Consumo por vehículo",
            esquema="operaciones",
            tabelas=["ops.trips", "ops.routes"],
            foco=(
                "Revisa el consumo de gasóleo por cada 100 km de cada vehículo "
                "en los viajes completados. Avísame de los vehículos cuyo "
                "consumo esté claramente por encima del resto de la flota, y "
                "dime cuánto gasóleo de más representa al año."
            ),
            frequencia="weekly",
            arquetipo="operations_monitor",
        ),
        Agente(
            nome="Rutas que incumplen el plazo",
            esquema="operaciones",
            tabelas=["ops.trips", "ops.routes"],
            foco=(
                "Compara la hora de llegada con la hora prevista en cada ruta. "
                "Dime qué rutas llegan tarde de forma sistemática y cuántos "
                "minutos de media. Una ruta que falla casi siempre no es "
                "tráfico: es un tiempo estándar mal estimado."
            ),
            frequencia="daily",
            arquetipo="operations_monitor",
        ),
        Agente(
            nome="Taller y disponibilidad",
            esquema="flota",
            tabelas=["fleet.maintenance_jobs", "fleet.vehicles"],
            foco=(
                "Vigila el coste de taller y los días fuera de la carretera por "
                "vehículo. Avísame cuando un vehículo acumule varias averías o "
                "cuando los días parados se concentren en pocas matrículas — un "
                "camión parado sigue teniendo renting, seguro e impuesto."
            ),
            frequencia="weekly",
            arquetipo="risk_radar",
        ),
        Agente(
            nome="Incidencias por cliente",
            esquema="carga",
            tabelas=["freight.shipments", "freight.clients"],
            foco=(
                "Agrupa las incidencias de carga (mercancía dañada, fallo de "
                "temperatura, documentación) por cliente y por tipo. Dime si "
                "alguna se concentra en un cliente concreto, porque eso deja de "
                "ser mala suerte y pasa a ser una conversación."
            ),
            frequencia="weekly",
            arquetipo="risk_radar",
        ),
        Agente(
            nome="Margen por cliente",
            esquema="carga",
            tabelas=["freight.shipments", "freight.clients"],
            foco=(
                "Calcula el importe facturado por tonelada y por porte de cada "
                "cliente, y compáralo con el mes anterior. Avísame de los "
                "clientes cuyo importe por tonelada esté bajando: la tarifa no "
                "se toca, pero el peso medio por porte sí."
            ),
            frequencia="monthly",
            arquetipo="financial_analyst",
        ),
    ],
)


# ── as perguntas ─────────────────────────────────────────────────────
#
# Cinco fios já respondidos. A resposta é função do resultado da
# consulta, não texto escrito à mão — ver `pecas.Pergunta`.

from scripts.demo_sectorial.formato import eur, euro2, n, pct  # noqa: E402
from scripts.demo_sectorial.pecas import Pergunta  # noqa: E402

P_FROTA = (
    _FROTA
    + """ SELECT plate, anio, ROUND(km) AS km,
       ROUND(coste / NULLIF(km, 0), 2) AS coste_km,
       ROUND(ingreso / NULLIF(km, 0), 2) AS ingreso_km,
       ROUND(ingreso - coste) AS aportacion
FROM frota ORDER BY ingreso - coste"""
)

P_VAZIO = """SELECT r.origin || ' - ' || r.destination AS trayecto,
       COUNT(*) AS viajes,
       COUNT(*) FILTER (WHERE s.id IS NULL) AS vacios,
       ROUND(SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END)) AS km_vacio,
       ROUND(SUM(CASE WHEN s.id IS NULL THEN t.fuel_litres * 1.62 ELSE 0 END)) AS gasoleo
FROM ops.trips t
JOIN ops.routes r ON r.id = t.route_id
LEFT JOIN freight.shipments s ON s.trip_id = t.id
WHERE t.status = 'completed'
GROUP BY r.id, r.origin, r.destination
HAVING COUNT(*) FILTER (WHERE s.id IS NULL) > 0
ORDER BY gasoleo DESC"""

P_PRAZOS = (
    "SELECT r.origin || ' - ' || r.destination AS ruta, COUNT(*) AS viajes, "
    "ROUND(100.0 * COUNT(*) FILTER (WHERE " + _FUERA + ") / COUNT(*), 1) AS fuera_pct, "
    "ROUND(AVG(EXTRACT(EPOCH FROM (t.arrived_at - t.planned_arrival)) / 60)) AS retraso_min "
    "FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id "
    "JOIN freight.shipments s ON s.trip_id = t.id "
    "JOIN freight.clients c ON c.id = s.client_id "
    "WHERE t.status = 'completed' "
    "GROUP BY r.id, r.origin, r.destination ORDER BY fuera_pct DESC"
)

P_CLIENTES = """SELECT c.name AS cliente,
       COUNT(*) AS portes,
       ROUND(SUM(s.revenue)) AS facturado,
       ROUND(SUM(s.revenue) / NULLIF(SUM(t.km_run), 0), 2) AS por_km,
       COUNT(*) FILTER (WHERE s.incident IS NOT NULL AND s.incident <> '') AS incidencias
FROM freight.shipments s
JOIN freight.clients c ON c.id = s.client_id
JOIN ops.trips t ON t.id = s.trip_id
GROUP BY c.id, c.name ORDER BY por_km DESC"""

P_TALLER = """SELECT v.plate AS matricula,
       EXTRACT(YEAR FROM v.acquired_on)::INT AS anio,
       COUNT(*) FILTER (WHERE m.kind = 'avaria') AS averias,
       ROUND(SUM(m.cost)) AS coste,
       SUM(m.days_off_road) AS dias
FROM fleet.vehicles v JOIN fleet.maintenance_jobs m ON m.vehicle_id = v.id
GROUP BY v.id, v.plate, v.acquired_on ORDER BY coste DESC"""


def _r_frota(linhas):
    """A lista tem de ser a dos que perdem, não os cinco primeiros.

    A primeira versão mostrava sempre `linhas[:5]` e escrevia por baixo
    «os que aparecem aqui custam mais por quilómetro do que ingressam».
    Com dois veículos a perder, três das cinco linhas contradiziam a
    frase debaixo delas — a resposta a desmentir a sua própria tabela, à
    frente de quem está a decidir se compra.
    """
    if not linhas:
        return "No hay viajes completados en el periodo."

    def linha(r):
        return (
            f"- {r['plate']} ({r['anio']}): {eur(r['aportacion'])} de "
            f"aportación, {n(r['km'])} km, coste {euro2(r['coste_km'])}/km "
            f"contra {euro2(r['ingreso_km'])}/km de ingreso"
        )

    perdem = [r for r in linhas if float(r["aportacion"]) < 0]
    if not perdem:
        detalhe = "\n".join(linha(r) for r in linhas[:3])
        return (
            f"{detalhe}\n\nNingún vehículo pierde dinero en el periodo. El que "
            f"menos aporta, {linhas[0]['plate']}, deja "
            f"{eur(linhas[0]['aportacion'])}.\n\n"
            "Lo que decide es el coste por kilómetro, no el total: un camión "
            "que rueda mucho cuesta más en absoluto y puede aportar más."
        )

    detalhe = "\n".join(linha(r) for r in perdem)
    seguintes = linhas[len(perdem) : len(perdem) + 2]
    comparacao = (
        "\n\nPara comparar, los dos siguientes:\n" + "\n".join(linha(r) for r in seguintes)
        if seguintes
        else ""
    )
    plural = "vehículo no se paga" if len(perdem) == 1 else "vehículos no se pagan"
    return (
        f"{detalhe}{comparacao}\n\n"
        f"**{len(perdem)} de {len(linhas)} {plural}**: cuestan más por "
        "kilómetro de lo que ingresan por kilómetro, y eso no se arregla "
        "dándoles más viajes.\n\n"
        "El total engaña: un camión que rueda mucho cuesta más en absoluto y "
        "aporta más. La línea que decide es el euro por kilómetro."
    )


def _r_vazio(linhas):
    if not linhas:
        return "No hay viajes en vacío en el periodo."
    total = sum(float(r["gasoleo"] or 0) for r in linhas)
    detalhe = "\n".join(
        f"- {r['trayecto']}: {r['vacios']} de {r['viajes']} viajes en vacío, "
        f"{n(r['km_vacio'])} km, {eur(r['gasoleo'])} de gasóleo"
        for r in linhas[:6]
    )
    return (
        f"{detalhe}\n\n"
        f"En total, **{eur(total)} de gasóleo quemado sin carga**.\n\n"
        "Esta línea no existe en ningún sistema: se define por una ausencia — "
        "un viaje al que no corresponde ningún porte. Por eso no aparece en "
        "ningún informe y por eso nadie la defiende en una reunión de costes."
    )


def _r_prazos(linhas):
    if not linhas:
        return "No hay viajes completados en el periodo."
    detalhe = "\n".join(
        f"- {r['ruta']}: {pct(r['fuera_pct'])} fuera de plazo sobre "
        f"{n(r['viajes'])} viajes, retraso medio {n(r['retraso_min'])} min"
        for r in linhas[:6]
    )
    pior = linhas[0]
    return (
        f"{detalhe}\n\n"
        f"La peor es **{pior['ruta']}**, con {pct(pior['fuera_pct'])}.\n\n"
        "El plazo es el del cliente, no un estándar interno: cada uno tiene el "
        "suyo, y la misma ruta cumple con uno e incumple con otro. Comparar "
        "rutas contra un único umbral es lo que hace que el problema no "
        "aparezca."
    )


def _r_clientes(linhas):
    if not linhas:
        return "No hay portes en el periodo."
    detalhe = "\n".join(
        f"- {r['cliente']}: {euro2(r['por_km'])}/km, {n(r['portes'])} portes, "
        f"{eur(r['facturado'])}, {r['incidencias']} incidencias"
        for r in linhas[:6]
    )
    melhor, pior = linhas[0], linhas[-1]
    return (
        f"{detalhe}\n\n"
        f"**{melhor['cliente']}** deja {euro2(melhor['por_km'])} por kilómetro "
        f"y **{pior['cliente']}** {euro2(pior['por_km'])}.\n\n"
        "El facturado total engaña: un cliente grande que pide trayectos largos "
        "y baratos puede estar por debajo de uno pequeño con rutas cortas. Lo "
        "que paga el camión es el euro por kilómetro."
    )


def _r_taller(linhas):
    if not linhas:
        return "No hay intervenciones de taller en el periodo."
    detalhe = "\n".join(
        f"- {r['matricula']} ({r['anio']}): {eur(r['coste'])}, {r['averias']} "
        f"averías, {r['dias']} días parado"
        for r in linhas[:6]
    )
    dias = sum(int(r["dias"] or 0) for r in linhas)
    return (
        f"{detalhe}\n\n"
        f"En conjunto, **{n(dias)} días fuera de la carretera**.\n\n"
        "El coste del taller es la mitad de la historia; la otra son los días "
        "parado, que no aparecen en ninguna factura. Un camión en el taller no "
        "cuesta solo la reparación: cuesta los viajes que no hizo."
    )


SECTOR.perguntas = [
    Pergunta(
        texto="¿Qué vehículos no se pagan?",
        esquemas=["flota", "operaciones", "carga"],
        sql=P_FROTA,
        pagina="Rentabilidad de flota",
        resposta=_r_frota,
    ),
    Pergunta(
        texto="¿Cuánto gasóleo quemamos en vacío, y en qué trayectos?",
        esquemas=["operaciones", "carga"],
        sql=P_VAZIO,
        pagina="Vacío de retorno",
        resposta=_r_vazio,
    ),
    Pergunta(
        texto="¿Qué rutas incumplen el plazo del cliente?",
        esquemas=["operaciones", "carga"],
        sql=P_PRAZOS,
        pagina="Plazos y servicio",
        resposta=_r_prazos,
    ),
    Pergunta(
        texto="¿Qué clientes dejan más por kilómetro?",
        esquemas=["carga", "operaciones"],
        sql=P_CLIENTES,
        pagina="Clientes y taller",
        resposta=_r_clientes,
    ),
    Pergunta(
        texto="¿Qué vehículos se nos están comiendo el taller?",
        esquemas=["flota"],
        sql=P_TALLER,
        pagina="Clientes y taller",
        resposta=_r_taller,
    ),
]
