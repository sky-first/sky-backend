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

from scripts.demo_sectorial.pecas import Agente, Pagina, Sector, grafico, kpi, tabela

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
                    "Coste medio por km", "kpi1", "operaciones",
                    _FROTA + " SELECT ROUND(SUM(coste) / NULLIF(SUM(km), 0), 2) AS v FROM frota",
                    legenda="Gasóleo, conductor, peajes, taller y coste fijo",
                    formato="currency",
                ),
                kpi(
                    "Ingreso medio por km", "kpi2", "carga",
                    _FROTA + " SELECT ROUND(SUM(ingreso) / NULLIF(SUM(km), 0), 2) AS v FROM frota",
                    legenda="Lo facturado dividido por todo lo rodado",
                    formato="currency",
                ),
                kpi(
                    "Vehículos que no se pagan", "kpi3", "flota",
                    _FROTA + " SELECT COUNT(*) AS v FROM frota WHERE ingreso < coste",
                    legenda="Ingresan menos de lo que cuestan",
                ),
                kpi(
                    "Diferencia entre las dos mitades", "kpi4", "flota",
                    _FROTA + """ SELECT ROUND(
                        (SELECT AVG(ingreso - coste) FROM frota
                          WHERE ingreso - coste > (SELECT AVG(ingreso - coste) FROM frota))
                      - (SELECT AVG(ingreso - coste) FROM frota
                          WHERE ingreso - coste <= (SELECT AVG(ingreso - coste) FROM frota))
                    ) AS v""",
                    legenda="Lo que la media flota baja aporta de menos, al año",
                    formato="currency",
                ),
                grafico(
                    "Aportación por vehículo", "esq1", "flota",
                    _FROTA + """ SELECT plate AS matricula,
                                        ROUND(ingreso - coste) AS aportacion
                                 FROM frota ORDER BY aportacion""",
                    variante="bar", x="matricula", y="aportacion",
                ),
                tabela(
                    "Coste e ingreso por kilómetro", "dir1", "flota",
                    _FROTA + """ SELECT plate AS "Matrícula",
                                        anio AS "Año",
                                        ROUND(km) AS "Km",
                                        ROUND(coste / NULLIF(km, 0), 2) AS "Coste/km",
                                        ROUND(ingreso / NULLIF(km, 0), 2) AS "Ingreso/km",
                                        ROUND(ingreso - coste) AS "Aportación"
                                 FROM frota ORDER BY ingreso - coste""",
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
                    "Kilómetros en vacío", "kpi1", "operaciones",
                    f"SELECT COALESCE(SUM(t.km_run), 0) AS v {_VAZIO} AND s.id IS NULL",
                    legenda="Viajes sin ninguna carga asociada",
                ),
                kpi(
                    "Del total rodado", "kpi2", "operaciones",
                    "SELECT ROUND(100.0 * SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END)"
                    f" / NULLIF(SUM(t.km_run), 0), 1) AS v {_VAZIO}",
                    legenda="Uno de cada cinco kilómetros", formato="percent",
                ),
                kpi(
                    "Gasóleo quemado sin carga", "kpi3", "operaciones",
                    "SELECT COALESCE(ROUND(SUM(t.fuel_litres * 1.62)), 0) AS v "
                    f"{_VAZIO} AND s.id IS NULL",
                    legenda="A 1,62 €/litro", formato="currency",
                ),
                kpi(
                    "El trayecto con más vacío", "kpi4", "operaciones",
                    "SELECT r.origin || ' - ' || r.destination AS v FROM ops.trips t "
                    "JOIN ops.routes r ON r.id = t.route_id "
                    "LEFT JOIN freight.shipments s ON s.trip_id = t.id "
                    "WHERE t.status = 'completed' AND s.id IS NULL "
                    "GROUP BY r.id, r.origin, r.destination "
                    "ORDER BY SUM(t.fuel_litres) DESC LIMIT 1",
                    legenda="Un retorno vacío repetido es un retorno sin vender",
                ),
                tabela(
                    "Vacío por trayecto", "larga1", "operaciones",
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
                    "Porcentaje en vacío, mes a mes", "larga2", "operaciones",
                    """SELECT TO_CHAR(DATE_TRUNC('month', t.departed_at), 'YYYY-MM') AS mes,
                              ROUND(100.0 * SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END)
                                    / NULLIF(SUM(t.km_run), 0), 1) AS pct
                       FROM ops.trips t
                       LEFT JOIN freight.shipments s ON s.trip_id = t.id
                       WHERE t.status = 'completed'
                       GROUP BY 1 ORDER BY 1""",
                    variante="line", x="mes", y="pct",
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
                    "Dentro del plazo del cliente", "kpi1", "carga",
                    "SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE NOT (" + _FUERA + "))"
                    f" / COUNT(*), 1) AS v {_PLAZO}",
                    legenda="La media tapa las dos rutas que fallan",
                    formato="percent",
                ),
                kpi(
                    "Portes fuera de plazo", "kpi2", "carga",
                    f"SELECT COUNT(*) AS v {_PLAZO} AND {_FUERA}",
                    legenda="Cada uno es una llamada del cliente",
                ),
                kpi(
                    "La peor ruta", "kpi3", "operaciones",
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
                    "Incidencias de carga", "kpi4", "carga",
                    "SELECT COUNT(*) AS v FROM freight.shipments WHERE incident IS NOT NULL",
                    legenda="Daños, temperatura y documentación",
                ),
                grafico(
                    "Puntualidad mes a mes", "esq1", "carga",
                    "SELECT TO_CHAR(DATE_TRUNC('month', t.departed_at), 'YYYY-MM') AS mes, "
                    "ROUND(100.0 * COUNT(*) FILTER (WHERE NOT (" + _FUERA + "))"
                    f" / COUNT(*), 1) AS pct {_PLAZO} GROUP BY 1 ORDER BY 1",
                    variante="line", x="mes", y="pct",
                ),
                tabela(
                    "Cumplimiento por ruta", "dir1", "operaciones",
                    'SELECT r.origin || \' - \' || r.destination AS "Ruta", '
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
                    "Mejor cliente por km", "kpi1", "carga",
                    "SELECT c.name AS v FROM freight.shipments s "
                    "JOIN ops.trips t ON t.id = s.trip_id "
                    "JOIN freight.clients c ON c.id = s.client_id "
                    "GROUP BY c.id, c.name "
                    "ORDER BY SUM(s.revenue) / NULLIF(SUM(t.km_run), 0) DESC LIMIT 1",
                    legenda="Facturación partida por kilómetros rodados",
                ),
                kpi(
                    "Facturado en el periodo", "kpi2", "carga",
                    "SELECT COALESCE(ROUND(SUM(revenue)), 0) AS v FROM freight.shipments",
                    legenda="12 meses de portes", formato="currency",
                ),
                kpi(
                    "Taller en el periodo", "kpi3", "flota",
                    "SELECT COALESCE(ROUND(SUM(cost)), 0) AS v FROM fleet.maintenance_jobs",
                    legenda="Avería, preventivo y neumáticos", formato="currency",
                ),
                kpi(
                    "Días fuera de la carretera", "kpi4", "flota",
                    "SELECT COALESCE(SUM(days_off_road), 0) AS v FROM fleet.maintenance_jobs",
                    legenda="Este coste no tiene factura, y por eso no entra en ninguna cuenta",
                ),
                grafico(
                    "Ingreso por kilómetro, por cliente", "esq1", "carga",
                    'SELECT c.name AS cliente, '
                    "ROUND(SUM(s.revenue) / NULLIF(SUM(t.km_run), 0), 2) AS eur_km "
                    "FROM freight.shipments s JOIN ops.trips t ON t.id = s.trip_id "
                    "JOIN freight.clients c ON c.id = s.client_id "
                    "GROUP BY c.id, c.name ORDER BY eur_km DESC",
                    variante="bar", x="cliente", y="eur_km",
                ),
                tabela(
                    "Taller por vehículo", "dir1", "flota",
                    'SELECT v.plate AS "Matrícula", '
                    'EXTRACT(YEAR FROM v.acquired_on)::INT AS "Año", '
                    "COUNT(*) FILTER (WHERE m.kind = 'avaria') AS \"Averías\", "
                    "COUNT(*) FILTER (WHERE m.kind = 'preventiva') AS \"Preventivo\", "
                    'ROUND(SUM(m.cost)) AS "Coste (€)", '
                    'SUM(m.days_off_road) AS "Días parado" '
                    "FROM fleet.vehicles v JOIN fleet.maintenance_jobs m ON m.vehicle_id = v.id "
                    "GROUP BY v.id, v.plate, v.acquired_on ORDER BY 5 DESC",
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
