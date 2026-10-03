# -*- coding: utf-8 -*-
"""Demonstração sectorial — Restauração, em castelhano.

Para uma rede de lojas de restauração rápida: 12 lojas, três formatos,
90 dias de operação, ~159 mil pedidos.

Dados em `scripts/demo/seed_restaurant.sql`. Sintéticos, de ninguém.

── As três perguntas ───────────────────────────────────────────────

1. **Onde é que o tempo de serviço se parte, e quando.** A média da rede
   esconde-o: duas lojas falham o prazo em seis de cada dez pedidos à
   hora de ponta, e as outras em dois. A média das duas com as dez dá um
   número que não manda ninguém a lado nenhum.

2. **Quanto custa a hora de pessoal por cada euro vendido.** O instinto
   diz que o problema está no pico, porque é quando a loja está cheia.
   Está ao contrário: ao jantar o pessoal é 13% das vendas e à noite é
   37%. O dinheiro está nas faixas vazias.

3. **O que se prepara e se deita fora.** A merma por validade não é a
   mesma coisa que a merma por excesso de preparação: a primeira é um
   problema de produto, a segunda é de previsão. Numa folha de turno são
   a mesma linha.

── Três ligações, pela mesma razão dos outros sectores ─────────────

Uma ligação Postgres vê um esquema só. As junções que atravessam
esquemas ficam nos painéis, pré-calculadas; os agentes ficam com
perguntas de um esquema, que é o que lhes permite correr ao vivo sem
mentir. Ver a nota longa em `transportes.py`.
"""

from __future__ import annotations

from scripts.demo_sectorial.pecas import Agente, Pagina, Sector, grafico, kpi, tabela

# ── blocos reutilizados ─────────────────────────────────────────────

_PRAZO = 240  # quatro minutos, do pedido à entrega
_PICO = "('comida', 'cena')"

_VENDAS_POR_FAIXA = """SELECT day_part, SUM(total) AS vendas, COUNT(*) AS pedidos
FROM service.orders GROUP BY day_part"""

_PESSOAL_POR_FAIXA = """SELECT day_part, SUM(hours * cost_per_hour) AS custo,
       SUM(hours) AS horas
FROM restaurant.staff_shifts GROUP BY day_part"""

SQL_SERVICO_POR_LOJA = f"""SELECT s.name AS store, s.format, s.city,
       COUNT(*) AS orders,
       ROUND(AVG(o.service_sec)) AS avg_sec,
       ROUND(100.0 * COUNT(*) FILTER (WHERE o.service_sec > {_PRAZO})
             / COUNT(*), 1) AS pct_over,
       ROUND(100.0 * COUNT(*) FILTER (
             WHERE o.service_sec > {_PRAZO} AND o.day_part IN {_PICO})
             / NULLIF(COUNT(*) FILTER (WHERE o.day_part IN {_PICO}), 0), 1)
             AS pct_over_peak
FROM service.orders o
JOIN restaurant.stores s ON s.id = o.store_id
GROUP BY s.id, s.name, s.format, s.city
ORDER BY pct_over_peak DESC"""

SQL_SERVICO_POR_FAIXA = f"""SELECT o.day_part,
       COUNT(*) AS orders,
       ROUND(AVG(o.service_sec)) AS avg_sec,
       ROUND(100.0 * COUNT(*) FILTER (WHERE o.service_sec > {_PRAZO})
             / COUNT(*), 1) AS pct_over
FROM service.orders o
GROUP BY o.day_part
ORDER BY pct_over DESC"""

SQL_PESSOAL = """WITH v AS (
    SELECT day_part, SUM(total) AS vendas, COUNT(*) AS pedidos
    FROM service.orders GROUP BY day_part
), p AS (
    SELECT day_part, SUM(hours * cost_per_hour) AS custo, SUM(hours) AS horas
    FROM restaurant.staff_shifts GROUP BY day_part
)
SELECT v.day_part,
       ROUND(v.vendas) AS sales,
       v.pedidos AS orders,
       ROUND(p.horas) AS hours,
       ROUND(p.custo) AS labour_cost,
       ROUND(100.0 * p.custo / NULLIF(v.vendas, 0), 1) AS labour_pct
FROM v JOIN p USING (day_part)
ORDER BY labour_pct DESC"""

SQL_MERMA = """SELECT p.name AS product, p.family, w.reason,
       SUM(w.units) AS units,
       ROUND(SUM(w.units * p.unit_cost)) AS cost,
       p.hold_minutes
FROM kitchen.waste w
JOIN kitchen.products p ON p.id = w.product_id
GROUP BY p.id, p.name, p.family, w.reason, p.hold_minutes
ORDER BY cost DESC
LIMIT 40"""

SQL_CANAL = """SELECT o.channel AS channel,
       COUNT(*) AS orders,
       ROUND(SUM(o.total)) AS sales,
       ROUND(AVG(o.total), 2) AS avg_ticket,
       ROUND(AVG(o.service_sec)) AS avg_sec
FROM service.orders o
GROUP BY o.channel
ORDER BY sales DESC"""

SQL_CARTA = """SELECT family,
       COUNT(*) AS items,
       ROUND(AVG(menu_price), 2) AS avg_price,
       ROUND(AVG(unit_cost), 2) AS avg_cost,
       ROUND(100.0 * AVG((menu_price - unit_cost) / NULLIF(menu_price, 0)), 1)
             AS margin_pct,
       ROUND(AVG(hold_minutes)) AS hold_min
FROM kitchen.products
GROUP BY family
ORDER BY margin_pct"""

# ── séries ───────────────────────────────────────────────────────────

SQL_SERIE_SERVICO = f"""SELECT TO_CHAR(DATE_TRUNC('week', o.placed_at), 'YYYY-MM-DD') AS t,
       ROUND(100.0 * COUNT(*) FILTER (WHERE o.service_sec > {_PRAZO})
             / COUNT(*), 1) AS v
FROM service.orders o
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_PESSOAL = """WITH v AS (
    SELECT day_part, SUM(total) AS vendas FROM service.orders GROUP BY day_part
), p AS (
    SELECT day_part, SUM(hours * cost_per_hour) AS custo
    FROM restaurant.staff_shifts GROUP BY day_part
)
SELECT v.day_part AS t,
       ROUND(100.0 * p.custo / NULLIF(v.vendas, 0), 1) AS v
FROM v JOIN p USING (day_part) ORDER BY v DESC"""

SQL_SERIE_MERMA = """SELECT w.reason AS t, ROUND(SUM(w.units * p.unit_cost)) AS v
FROM kitchen.waste w JOIN kitchen.products p ON p.id = w.product_id
GROUP BY w.reason ORDER BY v DESC"""

# ── valores escalares ────────────────────────────────────────────────

V = {
    "pedidos": "SELECT COUNT(*) FROM service.orders",
    "vendas": "SELECT COALESCE(ROUND(SUM(total)), 0) FROM service.orders",
    "ticket_medio": "SELECT ROUND(AVG(total), 2) FROM service.orders",
    "tempo_medio": "SELECT ROUND(AVG(service_sec)) FROM service.orders",
    "fora_do_prazo": (
        f"SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE service_sec > {_PRAZO})"
        " / COUNT(*), 1) FROM service.orders"
    ),
    "fora_do_prazo_no_pico": (
        f"SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE service_sec > {_PRAZO})"
        f" / COUNT(*), 1) FROM service.orders WHERE day_part IN {_PICO}"
    ),
    "pior_loja": (
        "SELECT s.name FROM service.orders o JOIN restaurant.stores s ON s.id = o.store_id "
        f"WHERE o.day_part IN {_PICO} GROUP BY s.id, s.name "
        f"ORDER BY 100.0 * COUNT(*) FILTER (WHERE o.service_sec > {_PRAZO}) / COUNT(*) DESC "
        "LIMIT 1"
    ),
    "lojas_fora_do_prazo": (
        "SELECT COUNT(*) FROM (SELECT s.id FROM service.orders o "
        "JOIN restaurant.stores s ON s.id = o.store_id "
        f"WHERE o.day_part IN {_PICO} GROUP BY s.id "
        f"HAVING 100.0 * COUNT(*) FILTER (WHERE o.service_sec > {_PRAZO}) / COUNT(*) > 40) x"
    ),
    "pessoal_total": (
        "SELECT COALESCE(ROUND(SUM(hours * cost_per_hour)), 0) FROM restaurant.staff_shifts"
    ),
    "pessoal_pct": (
        "SELECT ROUND(100.0 * (SELECT SUM(hours * cost_per_hour) FROM restaurant.staff_shifts)"
        " / NULLIF((SELECT SUM(total) FROM service.orders), 0), 1)"
    ),
    "faixa_mais_cara": (
        "WITH v AS (SELECT day_part, SUM(total) s FROM service.orders GROUP BY day_part), "
        "p AS (SELECT day_part, SUM(hours*cost_per_hour) c FROM restaurant.staff_shifts "
        "GROUP BY day_part) SELECT v.day_part FROM v JOIN p USING (day_part) "
        "ORDER BY p.c / NULLIF(v.s, 0) DESC LIMIT 1"
    ),
    "faixa_mais_barata": (
        "WITH v AS (SELECT day_part, SUM(total) s FROM service.orders GROUP BY day_part), "
        "p AS (SELECT day_part, SUM(hours*cost_per_hour) c FROM restaurant.staff_shifts "
        "GROUP BY day_part) SELECT v.day_part FROM v JOIN p USING (day_part) "
        "ORDER BY p.c / NULLIF(v.s, 0) LIMIT 1"
    ),
    "merma_total": (
        "SELECT COALESCE(ROUND(SUM(w.units * p.unit_cost)), 0) FROM kitchen.waste w "
        "JOIN kitchen.products p ON p.id = w.product_id"
    ),
    "merma_validade": (
        "SELECT COALESCE(ROUND(SUM(w.units * p.unit_cost)), 0) FROM kitchen.waste w "
        "JOIN kitchen.products p ON p.id = w.product_id WHERE w.reason = 'caducidad'"
    ),
    "merma_excesso": (
        "SELECT COALESCE(ROUND(SUM(w.units * p.unit_cost)), 0) FROM kitchen.waste w "
        "JOIN kitchen.products p ON p.id = w.product_id "
        "WHERE w.reason = 'preparado de más'"
    ),
    "familia_mais_perdida": (
        "SELECT p.family FROM kitchen.waste w JOIN kitchen.products p ON p.id = w.product_id "
        "GROUP BY p.family ORDER BY SUM(w.units * p.unit_cost) DESC LIMIT 1"
    ),
    "canal_maior": (
        "SELECT channel FROM service.orders GROUP BY channel ORDER BY SUM(total) DESC LIMIT 1"
    ),
    "canal_ticket_maior": (
        "SELECT channel FROM service.orders GROUP BY channel ORDER BY AVG(total) DESC LIMIT 1"
    ),
    "lojas": "SELECT COUNT(*) FROM restaurant.stores",
    "artigos": "SELECT COUNT(*) FROM kitchen.products",
    "margem_carta": (
        "SELECT ROUND(100.0 * AVG((menu_price - unit_cost) / NULLIF(menu_price, 0)), 1) "
        "FROM kitchen.products"
    ),
}

_FONTES = [
    ("service.orders", "Cada pedido: canal, hora, tempo e total",
     "Every order: channel, hour, time and total"),
    ("service.order_items", "O que foi vendido em cada pedido",
     "What was sold on each order"),
    ("kitchen.waste", "O que se preparou e não se vendeu",
     "What was prepared and not sold"),
    ("kitchen.products", "Custo, preço de carta e validade",
     "Cost, menu price and hold time"),
    ("restaurant.staff_shifts", "Quem esteve, quantas horas, a que custo",
     "Who was on, how many hours, at what cost"),
    ("restaurant.stores", "A loja e o seu formato",
     "The store and its format"),
]


def fontes(pt):
    return [{"table": t, "description": (a if pt else b)} for t, a, b in _FONTES]


def tile(rotulo, chave, formato=None):
    t = {"label": rotulo, "value_sql": V[chave]}
    if formato:
        t["format"] = formato
    return t


SECTOR = Sector(
    chave="restauracion",
    nome_do_projecto="Restauración — Operación de tiendas",
    descricao=(
        "Demostración sectorial: velocidad de servicio, coste de personal por "
        "euro vendido y merma, sobre 90 días y 12 tiendas."
    ),
    ligacoes={
        "tiendas": (
            "Tiendas",
            "restaurant",
            "Las tiendas y el cuadro de personal. El sistema que sabe quién "
            "estuvo y cuánto costó la hora.",
        ),
        "servicio": (
            "Servicio",
            "service",
            "Cada pedido: canal, hora, tiempo de entrega e importe. El sistema "
            "que sabe lo que se vendió y lo rápido que salió.",
        ),
        "cocina": (
            "Cocina",
            "kitchen",
            "Carta y merma: coste, precio, caducidad, y lo que se tiró. El "
            "sistema que sabe lo que se preparó de más.",
        ),
    },
    paginas=[
        Pagina(
            nome="Velocidad de servicio",
            descricao=(
                "La media de la red esconde el problema: dos tiendas fallan el "
                "plazo en seis de cada diez pedidos en hora punta, y el resto "
                "en dos."
            ),
            icone="clock",
            cor="#E05C5C",
            widgets=[
                # `duration` e não um número cru: o valor vem em segundos e
                # o cartão mostrava «204», que ninguém lê como 3m 24s.
                kpi("Tiempo medio de entrega", "kpi1", "servicio", V["tempo_medio"],
                    legenda="Del pedido a la entrega", formato="duration"),
                kpi("Fuera de los 4 minutos", "kpi2", "servicio", V["fora_do_prazo"],
                    legenda="Sobre todos los pedidos", formato="percent"),
                kpi("Fuera, en hora punta", "kpi3", "servicio", V["fora_do_prazo_no_pico"],
                    legenda="Comida y cena — donde se decide", formato="percent"),
                kpi("La tienda más lenta", "kpi4", "tiendas", V["pior_loja"],
                    legenda="Por incumplimiento en hora punta"),
                tabela("Cumplimiento por tienda", "larga1", "servicio", SQL_SERVICO_POR_LOJA),
                grafico("Fuera de plazo, semana a semana", "larga2", "servicio",
                        SQL_SERIE_SERVICO, variante="line", x="t", y="v"),
            ],
        ),
        Pagina(
            nome="Coste de personal",
            descricao=(
                "El instinto dice que el problema está en la hora punta, porque "
                "es cuando la tienda está llena. Está al revés."
            ),
            icone="users",
            cor="#F5A623",
            widgets=[
                kpi("Personal sobre ventas", "kpi1", "tiendas", V["pessoal_pct"],
                    legenda="En toda la red y el periodo", formato="percent"),
                kpi("Coste de personal", "kpi2", "tiendas", V["pessoal_total"],
                    legenda="90 días, 12 tiendas", formato="currency"),
                kpi("La franja más cara", "kpi3", "tiendas", V["faixa_mais_cara"],
                    legenda="Por euro de personal sobre euro vendido"),
                kpi("La más rentable", "kpi4", "tiendas", V["faixa_mais_barata"],
                    legenda="Donde la hora se paga sola"),
                tabela("Ventas y personal por franja", "esq1", "tiendas", SQL_PESSOAL),
                grafico("Personal sobre ventas, por franja", "dir1", "tiendas",
                        SQL_SERIE_PESSOAL, variante="bar", x="t", y="v"),
            ],
        ),
        Pagina(
            nome="Merma",
            descricao=(
                "Caducidad y exceso de preparación son dos problemas distintos: "
                "uno es de producto, el otro de previsión. En una hoja de turno "
                "son la misma línea."
            ),
            icone="trash",
            cor="#7B61FF",
            widgets=[
                kpi("Merma en el periodo", "kpi1", "cocina", V["merma_total"],
                    legenda="A coste, no a precio de carta", formato="currency"),
                kpi("Por caducidad", "kpi2", "cocina", V["merma_validade"],
                    legenda="Producto con vida corta — es de carta",
                    formato="currency"),
                kpi("Por preparar de más", "kpi3", "cocina", V["merma_excesso"],
                    legenda="Se preparó para una ola que no vino",
                    formato="currency"),
                kpi("La familia más perdida", "kpi4", "cocina", V["familia_mais_perdida"],
                    legenda="Por coste tirado"),
                tabela("Merma por artículo y motivo", "esq1", "cocina", SQL_MERMA),
                grafico("Merma por motivo", "dir1", "cocina", SQL_SERIE_MERMA,
                        variante="bar", x="t", y="v"),
            ],
        ),
        Pagina(
            nome="Canal y carta",
            descricao=(
                "Qué canal trae el importe y cuál trae el ticket, y qué familias "
                "de la carta sostienen el margen."
            ),
            icone="layers",
            cor="#4A90D9",
            widgets=[
                kpi("Pedidos servidos", "kpi1", "servicio", V["pedidos"],
                    legenda="90 días"),
                kpi("Ticket medio", "kpi2", "servicio", V["ticket_medio"],
                    legenda="Importe medio por pedido", formato="currency"),
                kpi("El canal que más vende", "kpi3", "servicio", V["canal_maior"],
                    legenda="Por importe, no por número"),
                kpi("Margen medio de carta", "kpi4", "cocina", V["margem_carta"],
                    legenda="Precio contra coste, por artículo", formato="percent"),
                grafico("Ventas por canal", "esq1", "servicio", SQL_CANAL,
                        variante="bar", x="channel", y="sales"),
                tabela("Margen por familia de carta", "dir1", "cocina", SQL_CARTA),
            ],
        ),
    ],
    agentes=[
        Agente(
            nome="Tiempos de servicio en hora punta",
            esquema="servicio",
            tabelas=["service.orders"],
            foco=(
                "Mira el tiempo de entrega de los pedidos en las franjas de "
                "comida y cena. Dime en qué tiendas y en qué días se pasa de "
                "los cuatro minutos con más frecuencia, y si eso empeoró "
                "respecto a las semanas anteriores. Una tienda lenta a la hora "
                "punta no es lo mismo que una tienda lenta siempre."
            ),
            frequencia="daily",
            arquetipo="operations_monitor",
        ),
        Agente(
            nome="Canales que suben y bajan",
            esquema="servicio",
            tabelas=["service.orders"],
            foco=(
                "Compara los pedidos y el importe por canal — mostrador, "
                "quiosco, drive, entrega — en las últimas semanas contra las "
                "anteriores. Avísame de los canales que estén perdiendo "
                "importe aunque mantengan el número de pedidos: eso es ticket "
                "medio que baja, no clientes que se van."
            ),
            frequencia="weekly",
            arquetipo="growth_intelligence",
        ),
        Agente(
            nome="Merma por motivo",
            esquema="cocina",
            tabelas=["kitchen.waste", "kitchen.products"],
            foco=(
                "Agrupa la merma por motivo y por artículo, valorada a coste. "
                "Separa la caducidad del exceso de preparación: la primera se "
                "corrige en la carta, la segunda en la previsión. Dime qué "
                "artículos concentran el coste."
            ),
            frequencia="weekly",
            arquetipo="operations_monitor",
        ),
        Agente(
            nome="Margen de carta por familia",
            esquema="cocina",
            tabelas=["kitchen.products"],
            foco=(
                "Compara el precio de carta con el coste unitario de cada "
                "artículo y agrúpalo por familia. Avísame de las familias cuyo "
                "margen esté por debajo del resto, y mira si coinciden con las "
                "de vida más corta — margen bajo con caducidad corta es la peor "
                "combinación que hay."
            ),
            frequencia="monthly",
            arquetipo="financial_analyst",
        ),
        Agente(
            nome="Horas de personal por tienda",
            esquema="tiendas",
            tabelas=["restaurant.staff_shifts", "restaurant.stores"],
            foco=(
                "Revisa las horas y el coste de personal por tienda y por "
                "franja. Dime qué tiendas tienen más horas en las franjas "
                "flojas y si alguna se desvía claramente de las demás con el "
                "mismo formato. El formato explica casi todo: comparar una "
                "tienda de carretera con una de centro comercial no dice nada."
            ),
            frequencia="weekly",
            arquetipo="operations_monitor",
        ),
    ],
)
