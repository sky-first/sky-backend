# -*- coding: utf-8 -*-
"""Verifica os dados sintéticos dos três projectos sectoriais.

    python scripts/demo/verificar_sectores.py "postgresql://user:pwd@host/base"

Só lê. Serve para duas coisas:

  * **o relatório** — os números que a bateria de perguntas de 14/10/2026
    apanhou iguais ou incoerentes (famílias, fornecedores, viaturas,
    lojas, portes do último mês). Corre igual sobre os seeds antigos e
    sobre os novos, por isso dá o antes e o depois;
  * **as invariantes** — o que tem de ser verdade nos dados para a
    demonstração não se desmentir em vídeo. O teste
    `src/tests/test_seeds_sectoriais_postgres.py` corre-as contra um
    Postgres a sério; aqui imprime-as com ✓/✗.

── Porque é que há um relatório e não só testes ────────────────────

Uma invariante diz "não há empates"; não diz se os números são bons de
mostrar. O relatório é para alguém OLHAR — foi por ninguém ter olhado
que 18 viaturas com 15 viagens cada uma chegaram a produção com os
testes todos verdes.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

# ── o relatório: só usa colunas que existem nos seeds antigos e novos ──

RELATORIO: list[tuple[str, str]] = [
    (
        "Alimentación · ventas por familia este año",
        """SELECT p.family AS familia,
                  ROUND(SUM(ol.quantity * ol.unit_price * (1 - ol.discount))) AS facturado,
                  SUM(ol.quantity) AS unidades
           FROM trade.order_lines ol
           JOIN trade.orders o ON o.id = ol.order_id
           JOIN warehouse.lots l ON l.id = ol.lot_id
           JOIN assortment.products p ON p.id = l.product_id
           WHERE o.ordered_at >= DATE_TRUNC('year', CURRENT_DATE)
           GROUP BY p.family ORDER BY facturado DESC""",
    ),
    (
        "Alimentación · referencias por proveedor",
        """SELECT s.name AS proveedor, COUNT(p.id) AS referencias
           FROM assortment.suppliers s
           LEFT JOIN assortment.products p ON p.supplier_id = s.id
           GROUP BY s.id, s.name ORDER BY referencias DESC""",
    ),
    (
        "Alimentación · capital en almacén y de guarda",
        """SELECT ROUND(SUM(s.quantity * p.unit_cost)) AS capital,
                  ROUND(SUM(s.quantity * p.unit_cost) FILTER (WHERE p.is_vintage)) AS guarda,
                  COUNT(DISTINCT p.id) FILTER (WHERE p.is_vintage AND s.quantity > 0)
                    AS refs_guarda_con_stock
           FROM warehouse.stock s
           JOIN warehouse.lots l ON l.id = s.lot_id
           JOIN assortment.products p ON p.id = l.product_id
           WHERE s.quantity > 0""",
    ),
    (
        "Alimentación · margen por canal",
        """SELECT c.channel AS canal,
                  ROUND(100.0 * SUM(ol.quantity * (ol.unit_price * (1 - ol.discount) - p.unit_cost))
                        / SUM(ol.quantity * ol.unit_price * (1 - ol.discount)), 1) AS bruto_pct,
                  ROUND(100.0 * SUM(ol.quantity * (ol.unit_price * (1 - ol.discount)
                                    * (1 - c.rebate_pct) - p.unit_cost))
                        / SUM(ol.quantity * ol.unit_price * (1 - ol.discount)), 1) AS neto_pct
           FROM trade.order_lines ol
           JOIN trade.orders o ON o.id = ol.order_id
           JOIN trade.customers c ON c.id = o.customer_id
           JOIN warehouse.lots l ON l.id = ol.lot_id
           JOIN assortment.products p ON p.id = l.product_id
           GROUP BY c.channel ORDER BY neto_pct""",
    ),
    (
        "Alimentación · pedidos por canal, último mes",
        """SELECT c.channel AS canal, COUNT(*) AS pedidos
           FROM trade.orders o JOIN trade.customers c ON c.id = o.customer_id
           WHERE o.ordered_at >= CURRENT_DATE - 30
           GROUP BY c.channel ORDER BY pedidos DESC""",
    ),
    (
        "Logística · viajes por vehículo, último mes (resumen)",
        """WITH x AS (
               SELECT v.plate, COUNT(t.id) AS viajes
               FROM fleet.vehicles v
               LEFT JOIN ops.trips t ON t.vehicle_id = v.id
                    AND t.departed_at >= CURRENT_DATE - 30
               GROUP BY v.plate)
           SELECT MIN(viajes) AS minimo, MAX(viajes) AS maximo,
                  COUNT(DISTINCT viajes) AS valores_distintos, SUM(viajes) AS total
           FROM x""",
    ),
    (
        "Logística · envíos del último mes: total, tarde, suma por cliente",
        """WITH e AS (
               SELECT s.id, s.client_id,
                      t.arrived_at > t.planned_arrival
                          + (c.sla_minutes * INTERVAL '1 minute') AS tarde
               FROM freight.shipments s
               JOIN ops.trips t ON t.id = s.trip_id
               JOIN freight.clients c ON c.id = s.client_id
               WHERE t.departed_at >= CURRENT_DATE - 30)
           SELECT COUNT(*) AS envios,
                  COUNT(*) FILTER (WHERE tarde) AS tarde,
                  (SELECT SUM(n) FROM (SELECT COUNT(*) AS n FROM e GROUP BY client_id) k)
                    AS suma_por_cliente,
                  (SELECT MIN(n) FROM (SELECT COUNT(*) AS n FROM e GROUP BY client_id) k)
                    AS min_cliente,
                  (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM e GROUP BY client_id) k)
                    AS max_cliente
           FROM e""",
    ),
    (
        "Logística · envíos por cliente este año",
        """SELECT c.name AS cliente, COUNT(*) AS envios
           FROM freight.shipments s
           JOIN ops.trips t ON t.id = s.trip_id
           JOIN freight.clients c ON c.id = s.client_id
           WHERE t.departed_at >= DATE_TRUNC('year', CURRENT_DATE)
           GROUP BY c.name ORDER BY envios DESC""",
    ),
    (
        "Logística · cumplimiento por ruta (las 4 peores)",
        """SELECT r.origin || ' - ' || r.destination AS ruta,
                  ROUND(100.0 * COUNT(*) FILTER (WHERE t.arrived_at > t.planned_arrival
                        + (c.sla_minutes * INTERVAL '1 minute')) / COUNT(*), 1) AS fuera_pct
           FROM ops.trips t
           JOIN ops.routes r ON r.id = t.route_id
           JOIN freight.shipments s ON s.trip_id = t.id
           JOIN freight.clients c ON c.id = s.client_id
           WHERE t.status = 'completed'
           GROUP BY r.id, r.origin, r.destination ORDER BY fuera_pct DESC LIMIT 4""",
    ),
    (
        "Restauración · pedidos por tienda, último mes",
        """SELECT s.name AS tienda, s.city AS ciudad, COUNT(*) AS pedidos
           FROM service.orders o JOIN restaurant.stores s ON s.id = o.store_id
           WHERE o.placed_at >= CURRENT_DATE - 30
           GROUP BY s.id, s.name, s.city ORDER BY pedidos DESC""",
    ),
    (
        "Restauración · 5 platos más vendidos, últimos 7 días",
        """SELECT p.name AS plato, SUM(oi.quantity) AS unidades
           FROM service.order_items oi
           JOIN service.orders o ON o.id = oi.order_id
           JOIN kitchen.products p ON p.id = oi.product_id
           WHERE o.placed_at >= CURRENT_DATE - 7
           GROUP BY p.name ORDER BY unidades DESC LIMIT 5""",
    ),
    (
        "Restauración · fuera de plazo en hora punta, por tienda",
        """SELECT s.name AS tienda,
                  ROUND(100.0 * COUNT(*) FILTER (WHERE o.service_sec > 240)
                        / COUNT(*), 1) AS fuera_pct
           FROM service.orders o JOIN restaurant.stores s ON s.id = o.store_id
           WHERE o.day_part IN ('comida', 'cena')
           GROUP BY s.id, s.name ORDER BY fuera_pct DESC""",
    ),
]


# ── as invariantes ──────────────────────────────────────────────────
#
# (nome, SQL, predicado sobre as linhas). O SQL devolve uma linha com
# as colunas que o predicado lê. Escritas para os seeds NOVOS — usam as
# colunas acrescentadas a 15/10/2026.

Predicado = Callable[[list[dict[str, Any]]], bool]

INVARIANTES: list[tuple[str, str, Predicado]] = [
    # ── alimentación ──
    (
        "72 referências e 360 lotes (a demo pública escreve estes números)",
        "SELECT (SELECT COUNT(*) FROM assortment.products) AS refs, "
        "(SELECT COUNT(*) FROM warehouse.lots) AS lotes",
        lambda r: r[0]["refs"] == 72 and r[0]["lotes"] == 360,
    ),
    (
        "as seis famílias vendem valores diferentes este ano",
        """SELECT COUNT(DISTINCT v) AS distintos, COUNT(*) AS familias,
                  MAX(v) / NULLIF(MIN(v), 0) AS razao
           FROM (SELECT p.family, SUM(ol.quantity * ol.unit_price) AS v
                 FROM trade.order_lines ol
                 JOIN trade.orders o ON o.id = ol.order_id
                 JOIN warehouse.lots l ON l.id = ol.lot_id
                 JOIN assortment.products p ON p.id = l.product_id
                 WHERE o.ordered_at >= DATE_TRUNC('year', CURRENT_DATE)
                 GROUP BY p.family) x""",
        lambda r: r[0]["familias"] == 6 and r[0]["distintos"] == 6 and r[0]["razao"] > 1.5,
    ),
    (
        "fornecedores com catálogos de tamanhos diferentes",
        """SELECT COUNT(DISTINCT n) AS distintos, MIN(n) AS minimo, MAX(n) AS maximo
           FROM (SELECT COUNT(*) AS n FROM assortment.products GROUP BY supplier_id) x""",
        lambda r: r[0]["distintos"] >= 5 and r[0]["maximo"] - r[0]["minimo"] >= 5,
    ),
    (
        "há vinho de guarda em stock, visto pelo catálogo e pelo armazém sozinho",
        """SELECT (SELECT SUM(s.quantity * p.unit_cost) FROM warehouse.stock s
                     JOIN warehouse.lots l ON l.id = s.lot_id
                     JOIN assortment.products p ON p.id = l.product_id
                    WHERE s.quantity > 0 AND p.is_vintage) AS pelo_catalogo,
                  (SELECT SUM(s.quantity * l.unit_cost) FROM warehouse.stock s
                     JOIN warehouse.lots l ON l.id = s.lot_id
                    WHERE s.quantity > 0 AND s.zone = 'bodega de guarda') AS pelo_armazem,
                  (SELECT SUM(s.quantity * p.unit_cost) FROM warehouse.stock s
                     JOIN warehouse.lots l ON l.id = s.lot_id
                     JOIN assortment.products p ON p.id = l.product_id
                    WHERE s.quantity > 0) AS total""",
        lambda r: r[0]["pelo_catalogo"] > 0
        and r[0]["pelo_catalogo"] == r[0]["pelo_armazem"]
        and 0.08 < r[0]["pelo_catalogo"] / r[0]["total"] < 0.6,
    ),
    (
        "o custo do lote e da linha é o da referência (uma só definição de margem)",
        """SELECT (SELECT COUNT(*) FROM warehouse.lots l
                     JOIN assortment.products p ON p.id = l.product_id
                    WHERE l.unit_cost <> p.unit_cost) AS lotes_diferentes,
                  (SELECT COUNT(*) FROM trade.order_lines ol
                     JOIN warehouse.lots l ON l.id = ol.lot_id
                     JOIN assortment.products p ON p.id = l.product_id
                    WHERE ol.unit_cost <> p.unit_cost) AS linhas_diferentes""",
        lambda r: r[0]["lotes_diferentes"] == 0 and r[0]["linhas_diferentes"] == 0,
    ),
    (
        "margem líquida: distribuidor < hotel e restaurante < tienda, e em gama real",
        """SELECT c.channel,
                  100.0 * SUM(ol.quantity * (ol.unit_price * (1 - ol.discount)
                              * (1 - c.rebate_pct) - ol.unit_cost))
                        / SUM(ol.quantity * ol.unit_price * (1 - ol.discount)) AS neto,
                  100.0 * SUM(ol.quantity * (ol.unit_price * (1 - ol.discount) - ol.unit_cost))
                        / SUM(ol.quantity * ol.unit_price * (1 - ol.discount)) AS bruto
           FROM trade.order_lines ol
           JOIN trade.orders o ON o.id = ol.order_id
           JOIN trade.customers c ON c.id = o.customer_id
           GROUP BY c.channel""",
        lambda r: (
            (m := {x["channel"]: float(x["neto"]) for x in r})
            and m["distribuidor"] < min(m["hotel"], m["restaurante"])
            and max(m["hotel"], m["restaurante"]) < m["tienda"]
            and all(5 < v < 40 for v in m.values())
            # a tese da página "Margen real": o líquido diverge mais do que o bruto
            and (max(m.values()) - min(m.values()))
            > (max(float(x["bruto"]) for x in r) - min(float(x["bruto"]) for x in r))
        ),
    ),
    (
        "quatro referências nunca venderam e têm stock",
        """SELECT COUNT(*) AS n FROM assortment.products p
           WHERE NOT EXISTS (SELECT 1 FROM trade.order_lines ol
                             JOIN warehouse.lots l ON l.id = ol.lot_id
                             WHERE l.product_id = p.id)
             AND EXISTS (SELECT 1 FROM warehouse.stock s
                         JOIN warehouse.lots l ON l.id = s.lot_id
                         WHERE l.product_id = p.id AND s.quantity > 0)""",
        lambda r: r[0]["n"] == 4,
    ),
    (
        "a linha aponta para um lote que já tinha entrado",
        """SELECT COUNT(*) AS n FROM trade.order_lines ol
           JOIN trade.orders o ON o.id = ol.order_id
           JOIN warehouse.lots l ON l.id = ol.lot_id
           WHERE l.received_on > o.ordered_at""",
        lambda r: r[0]["n"] == 0,
    ),
    (
        "o lote vale o que se vendeu dele mais o que resta",
        """SELECT COUNT(*) AS n FROM warehouse.lots l
           JOIN warehouse.stock s ON s.lot_id = l.id
           WHERE l.quantity <> s.quantity + COALESCE(
                 (SELECT SUM(quantity) FROM trade.order_lines WHERE lot_id = l.id), 0)
             AND l.quantity > 1""",
        lambda r: r[0]["n"] == 0,
    ),
    (
        "há caducado, a caducar em 60 dias, e encomendas de hoje para trás — nunca do futuro",
        """SELECT (SELECT COUNT(*) FROM warehouse.stock s JOIN warehouse.lots l ON l.id = s.lot_id
                    JOIN assortment.products p ON p.id = l.product_id
                    WHERE s.quantity > 0 AND NOT p.is_vintage
                      AND l.best_before < CURRENT_DATE) AS caducados,
                  (SELECT COUNT(*) FROM warehouse.stock s JOIN warehouse.lots l ON l.id = s.lot_id
                    JOIN assortment.products p ON p.id = l.product_id
                    WHERE s.quantity > 0 AND NOT p.is_vintage
                      AND l.best_before >= CURRENT_DATE
                      AND l.best_before < CURRENT_DATE + 60) AS a_caducar,
                  (SELECT MAX(ordered_at) FROM trade.orders) AS ultima,
                  (SELECT COUNT(*) FROM trade.orders WHERE ordered_at >= CURRENT_DATE - 7) AS semana""",
        lambda r: r[0]["caducados"] > 0
        and r[0]["a_caducar"] > 0
        and r[0]["semana"] > 0
        and str(r[0]["ultima"]) <= str(__import__("datetime").date.today()),
    ),
    # ── logística ──
    (
        "viagens por viatura no último mês variam",
        """SELECT COUNT(DISTINCT n) AS distintos, MIN(n) AS minimo, MAX(n) AS maximo
           FROM (SELECT v.id, COUNT(t.id) AS n FROM fleet.vehicles v
                 LEFT JOIN ops.trips t ON t.vehicle_id = v.id
                      AND t.departed_at >= CURRENT_DATE - 30
                 GROUP BY v.id) x""",
        lambda r: r[0]["distintos"] >= 6 and r[0]["maximo"] - r[0]["minimo"] >= 8,
    ),
    (
        "o porte tem as horas da viagem (expedido, prometido, entregue)",
        """SELECT COUNT(*) AS n FROM freight.shipments s JOIN ops.trips t ON t.id = s.trip_id
           WHERE s.shipped_at IS DISTINCT FROM t.departed_at
              OR s.promised_at IS DISTINCT FROM t.planned_arrival
              OR s.delivered_at IS DISTINCT FROM t.arrived_at""",
        lambda r: r[0]["n"] == 0,
    ),
    (
        "último mês, só em Carga: tarde ⊂ total, e por cliente soma o total",
        """WITH e AS (
               SELECT s.client_id,
                      s.delivered_at > s.promised_at + (c.sla_minutes * INTERVAL '1 minute') AS tarde
               FROM freight.shipments s JOIN freight.clients c ON c.id = s.client_id
               WHERE s.shipped_at >= CURRENT_DATE - 30)
           SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE tarde) AS tarde,
                  (SELECT SUM(n) FROM (SELECT COUNT(*) AS n FROM e GROUP BY client_id) k) AS soma,
                  (SELECT COUNT(*) FROM (SELECT 1 FROM e GROUP BY client_id) k) AS clientes
           FROM e""",
        lambda r: 150 < r[0]["total"] < 900
        and 0 < r[0]["tarde"] < r[0]["total"] * 0.4
        and r[0]["soma"] == r[0]["total"]
        and r[0]["clientes"] == 12,
    ),
    (
        "o mesmo «tarde» contado pela viagem e pelo porte",
        """SELECT (SELECT COUNT(*) FROM freight.shipments s JOIN ops.trips t ON t.id = s.trip_id
                     JOIN freight.clients c ON c.id = s.client_id
                    WHERE t.status = 'completed'
                      AND t.arrived_at > t.planned_arrival + (c.sla_minutes * INTERVAL '1 minute'))
                    AS pela_viagem,
                  (SELECT COUNT(*) FROM freight.shipments s JOIN freight.clients c ON c.id = s.client_id
                    WHERE s.delivered_at > s.promised_at + (c.sla_minutes * INTERVAL '1 minute'))
                    AS pelo_porte""",
        lambda r: r[0]["pela_viagem"] == r[0]["pelo_porte"] > 0,
    ),
    (
        "nenhuma viagem nem porte no futuro",
        """SELECT (SELECT COUNT(*) FROM ops.trips WHERE arrived_at > now()) +
                  (SELECT COUNT(*) FROM freight.shipments WHERE delivered_at > now()) +
                  (SELECT COUNT(*) FROM fleet.maintenance_jobs WHERE done_on >= CURRENT_DATE) AS n""",
        lambda r: r[0]["n"] == 0,
    ),
    (
        "clientes de tamanhos diferentes no ano (ninguém com um porte por dia certinho)",
        """SELECT MAX(n)::FLOAT / NULLIF(MIN(n), 0) AS razao, COUNT(DISTINCT n) AS distintos
           FROM (SELECT client_id, COUNT(*) AS n FROM freight.shipments
                 WHERE shipped_at >= CURRENT_DATE - 365 GROUP BY client_id) x""",
        lambda r: r[0]["razao"] > 2.5 and r[0]["distintos"] >= 10,
    ),
    (
        "o peso nunca passa a capacidade da viatura",
        """SELECT COUNT(*) AS n FROM freight.shipments s JOIN ops.trips t ON t.id = s.trip_id
           JOIN fleet.vehicles v ON v.id = t.vehicle_id WHERE s.weight_kg > v.capacity_kg""",
        lambda r: r[0]["n"] == 0,
    ),
    (
        "as três velhas gastam mais e param mais",
        """SELECT (SELECT ARRAY_AGG(vehicle_id ORDER BY l100 DESC) FROM (
                     SELECT t.vehicle_id, SUM(t.fuel_litres) / SUM(t.km_run) AS l100
                     FROM ops.trips t JOIN fleet.vehicles v ON v.id = t.vehicle_id
                     WHERE v.class <> 'ligeiro' GROUP BY t.vehicle_id) x) AS consumo,
                  (SELECT ARRAY_AGG(vehicle_id ORDER BY d DESC) FROM (
                     SELECT vehicle_id, SUM(days_off_road) AS d FROM fleet.maintenance_jobs
                     GROUP BY vehicle_id) y) AS parados""",
        lambda r: set(r[0]["parados"][:3]) == {3, 9, 14} and {9, 14} <= set(r[0]["consumo"][:3]),
    ),
    (
        "as rotas 4 e 11 são as piores e falham em mais de metade dos portes",
        """SELECT ARRAY_AGG(rid ORDER BY pct DESC) AS ordem, MIN(pct) FILTER (WHERE rid IN (4, 11)) AS pior_min,
                  MAX(pct) FILTER (WHERE rid NOT IN (4, 11)) AS resto_max
           FROM (SELECT t.route_id AS rid,
                        100.0 * COUNT(*) FILTER (WHERE t.arrived_at > t.planned_arrival
                              + (c.sla_minutes * INTERVAL '1 minute')) / COUNT(*) AS pct
                 FROM ops.trips t JOIN freight.shipments s ON s.trip_id = t.id
                 JOIN freight.clients c ON c.id = s.client_id
                 WHERE t.status = 'completed' GROUP BY t.route_id) x""",
        lambda r: set(r[0]["ordem"][:2]) == {4, 11}
        and r[0]["pior_min"] > 50
        and r[0]["resto_max"] < 25,
    ),
    (
        "um quinto dos quilómetros em vazio",
        """SELECT 100.0 * SUM(CASE WHEN s.id IS NULL THEN t.km_run ELSE 0 END) / SUM(t.km_run) AS pct
           FROM ops.trips t LEFT JOIN freight.shipments s ON s.trip_id = t.id
           WHERE t.status = 'completed'""",
        lambda r: 15 < r[0]["pct"] < 27,
    ),
    (
        "nem todas as viaturas se pagam, mas a maioria sim (e as velhas estão entre as piores)",
        """WITH custo AS (
               SELECT t.vehicle_id, SUM(t.km_run) AS km,
                      SUM(t.fuel_litres * 1.62 + t.driver_hours * d.cost_per_hour + r.toll_cost) AS var
               FROM ops.trips t JOIN fleet.drivers d ON d.id = t.driver_id
               JOIN ops.routes r ON r.id = t.route_id WHERE t.status = 'completed'
               GROUP BY t.vehicle_id),
           of AS (SELECT vehicle_id, SUM(cost) AS c FROM fleet.maintenance_jobs GROUP BY vehicle_id),
           rec AS (SELECT t.vehicle_id, SUM(s.revenue) AS i FROM ops.trips t
                   JOIN freight.shipments s ON s.trip_id = t.id GROUP BY t.vehicle_id),
           f AS (SELECT v.id, i.i - (c.var + COALESCE(o.c, 0) + v.fixed_cost_month * 12) AS aporta
                 FROM fleet.vehicles v JOIN custo c ON c.vehicle_id = v.id
                 LEFT JOIN of o ON o.vehicle_id = v.id LEFT JOIN rec i ON i.vehicle_id = v.id)
           SELECT COUNT(*) FILTER (WHERE aporta < 0) AS perdem,
                  (SELECT ARRAY_AGG(id ORDER BY aporta) FROM f) AS ordem
           FROM f""",
        lambda r: 1 <= r[0]["perdem"] <= 6 and len({3, 9, 14} & set(r[0]["ordem"][:5])) >= 2,
    ),
    # ── restauración ──
    (
        "lojas com volumes diferentes no último mês",
        """SELECT COUNT(DISTINCT n) AS distintos, MAX(n)::FLOAT / MIN(n) AS razao
           FROM (SELECT store_id, COUNT(*) AS n FROM service.orders
                 WHERE placed_at >= CURRENT_DATE - 30 GROUP BY store_id) x""",
        lambda r: r[0]["distintos"] == 12 and r[0]["razao"] > 1.6,
    ),
    (
        "os cinco pratos da semana não são cinco números iguais",
        """SELECT MAX(u)::FLOAT / MIN(u) AS razao FROM (
               SELECT SUM(oi.quantity) AS u FROM service.order_items oi
               JOIN service.orders o ON o.id = oi.order_id
               WHERE o.placed_at >= CURRENT_DATE - 7
               GROUP BY oi.product_id ORDER BY u DESC LIMIT 5) x""",
        lambda r: r[0]["razao"] > 1.25,
    ),
    (
        "as lojas 3 e 8 falham a hora de ponta; as outras não",
        """SELECT MIN(pct) FILTER (WHERE store_id IN (3, 8)) AS lentas_min,
                  MAX(pct) FILTER (WHERE store_id NOT IN (3, 8)) AS resto_max
           FROM (SELECT store_id, 100.0 * COUNT(*) FILTER (WHERE service_sec > 240) / COUNT(*) AS pct
                 FROM service.orders WHERE day_part IN ('comida', 'cena') GROUP BY store_id) x""",
        lambda r: r[0]["lentas_min"] > 45 and r[0]["resto_max"] < 35,
    ),
    (
        "o pessoal pesa mais numa faixa vazia do que na hora de ponta",
        """WITH v AS (SELECT day_part, SUM(total) AS s FROM service.orders GROUP BY day_part),
                p AS (SELECT day_part, SUM(hours * cost_per_hour) AS c FROM restaurant.staff_shifts
                      GROUP BY day_part)
           SELECT (SELECT v.day_part FROM v JOIN p USING (day_part) ORDER BY p.c / v.s DESC LIMIT 1) AS cara,
                  (SELECT v.day_part FROM v JOIN p USING (day_part) ORDER BY p.c / v.s LIMIT 1) AS barata""",
        lambda r: r[0]["cara"] not in ("comida", "cena") and r[0]["barata"] in ("comida", "cena"),
    ),
    (
        "o mostrador traz o importe e a entrega traz o ticket",
        """SELECT (SELECT channel FROM service.orders GROUP BY channel ORDER BY SUM(total) DESC LIMIT 1) AS importe,
                  (SELECT channel FROM service.orders GROUP BY channel ORDER BY AVG(total) DESC LIMIT 1) AS ticket""",
        lambda r: r[0]["importe"] == "mostrador" and r[0]["ticket"] == "entrega",
    ),
    (
        "nenhum pedido vazio, e o total bate com as linhas",
        """SELECT (SELECT COUNT(*) FROM service.orders o WHERE NOT EXISTS
                     (SELECT 1 FROM service.order_items i WHERE i.order_id = o.id)) AS vazios,
                  (SELECT COUNT(*) FROM service.orders o WHERE o.total <>
                     (SELECT ROUND(SUM(quantity * unit_price), 2) FROM service.order_items i
                      WHERE i.order_id = o.id)) AS desacertos""",
        lambda r: r[0]["vazios"] == 0 and r[0]["desacertos"] == 0,
    ),
    (
        "nada no futuro, e há pedidos dos últimos dias",
        """SELECT (SELECT COUNT(*) FROM service.orders WHERE placed_at > now()) AS futuros,
                  (SELECT COUNT(*) FROM service.orders WHERE placed_at >= CURRENT_DATE - 2) AS recentes,
                  (SELECT COUNT(*) FROM kitchen.waste WHERE wasted_on >= CURRENT_DATE) AS merma_hoje""",
        lambda r: r[0]["futuros"] == 0 and r[0]["recentes"] > 0 and r[0]["merma_hoje"] == 0,
    ),
    (
        "uma água não custa mais do que um hambúrguer, e a margem varia dentro da família",
        """SELECT (SELECT unit_cost FROM kitchen.products WHERE name = 'Agua') AS agua,
                  (SELECT unit_cost FROM kitchen.products WHERE name = 'Clásica') AS classica,
                  (SELECT COUNT(DISTINCT ROUND((menu_price - unit_cost) / menu_price, 3))
                     FROM kitchen.products WHERE family = 'Hamburguesas') AS margens""",
        lambda r: r[0]["agua"] < r[0]["classica"] and r[0]["margens"] >= 5,
    ),
]


def _linhas(cur, sql: str) -> list[dict[str, Any]]:
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def relatorio(cur) -> str:
    saida = []
    for titulo, sql in RELATORIO:
        saida.append(f"\n## {titulo}")
        for linha in _linhas(cur, sql):
            saida.append("   " + " | ".join(f"{k}={v}" for k, v in linha.items()))
    return "\n".join(saida)


def invariantes(cur) -> list[tuple[str, bool, list[dict[str, Any]]]]:
    resultado = []
    for nome, sql, ok in INVARIANTES:
        linhas = _linhas(cur, sql)
        try:
            passou = bool(ok(linhas))
        except Exception:  # noqa: BLE001 — uma linha inesperada é um ✗, não um traceback
            passou = False
        resultado.append((nome, passou, linhas))
    return resultado


def main() -> int:
    import psycopg2

    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with psycopg2.connect(sys.argv[1]) as conn, conn.cursor() as cur:
        conn.set_session(readonly=True)
        print(relatorio(cur))
        print("\n## Invariantes")
        falhas = 0
        for nome, passou, linhas in invariantes(cur):
            falhas += not passou
            print(f"   {'✓' if passou else '✗'} {nome}" + ("" if passou else f"  → {linhas}"))
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
