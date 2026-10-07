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

from scripts.demo_sectorial.formato import eur, euro2, n, pct
from scripts.demo_sectorial.pecas import (
    AMBAR,
    AZUL,
    VERDE,
    Agente,
    Metrica,
    Pagina,
    Pergunta,
    Sector,
    Termo,
    grafico,
    kpi,
    paragrafos,
    tabela,
    texto,
)

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

# O `AS day_part` é explícito porque esta consulta passou a alimentar
# TAMBÉM um gráfico, e o `mapping` do gráfico aponta a nomes de colunas.
# Sem o alias o Postgres devolve a coluna com o mesmo nome e tudo
# funciona — mas a garantia passa a depender de uma convenção em vez de
# uma declaração, e foi assim que um `SELECT o.channel` sem alias
# chegou a quebrar um gráfico.
SQL_SERVICO_POR_FAIXA = f"""SELECT o.day_part AS day_part,
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
       -- Duas casas e não zero: a resposta à pergunta soma esta coluna
       -- por motivo, e com os euros já arredondados por artigo o total
       -- saía 9.847 € onde o cartão dizia 9.846 €. Um euro de diferença
       -- entre dois sítios do mesmo ecrã custa mais confiança do que
       -- vale.
       ROUND(SUM(w.units * p.unit_cost), 2) AS cost,
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
    (
        "service.orders",
        "Cada pedido: canal, hora, tempo e total",
        "Every order: channel, hour, time and total",
    ),
    ("service.order_items", "O que foi vendido em cada pedido", "What was sold on each order"),
    ("kitchen.waste", "O que se preparou e não se vendeu", "What was prepared and not sold"),
    ("kitchen.products", "Custo, preço de carta e validade", "Cost, menu price and hold time"),
    (
        "restaurant.staff_shifts",
        "Quem esteve, quantas horas, a que custo",
        "Who was on, how many hours, at what cost",
    ),
    ("restaurant.stores", "A loja e o seu formato", "The store and its format"),
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
                kpi(
                    "Tiempo medio de entrega",
                    "kpi1",
                    "servicio",
                    V["tempo_medio"],
                    legenda="Del pedido a la entrega",
                    formato="duration",
                ),
                kpi(
                    "Fuera de los 4 minutos",
                    "kpi2",
                    "servicio",
                    V["fora_do_prazo"],
                    legenda="Sobre todos los pedidos",
                    formato="percent",
                ),
                kpi(
                    "Fuera, en hora punta",
                    "kpi3",
                    "servicio",
                    V["fora_do_prazo_no_pico"],
                    legenda="Comida y cena — donde se decide",
                    formato="percent",
                ),
                kpi(
                    "La tienda más lenta",
                    "kpi4",
                    "tiendas",
                    V["pior_loja"],
                    legenda="Por incumplimiento en hora punta",
                ),
                tabela("Cumplimiento por tienda", "larga1", "servicio", SQL_SERVICO_POR_LOJA),
                grafico(
                    "Fuera de plazo, semana a semana",
                    "larga2",
                    "servicio",
                    SQL_SERIE_SERVICO,
                    variante="line",
                    x="t",
                    y="v",
                ),
                texto(
                    "La media no le manda a ningún sitio",
                    "terco1a",
                    "servicio",
                    f"""WITH tienda AS (
                            SELECT s.id,
                                   100.0 * COUNT(*) FILTER (
                                       WHERE o.service_sec > {_PRAZO}
                                             AND o.day_part IN {_PICO})
                                   / NULLIF(COUNT(*) FILTER (
                                       WHERE o.day_part IN {_PICO}), 0) AS pico
                            FROM service.orders o
                            JOIN restaurant.stores s ON s.id = o.store_id
                            GROUP BY s.id
                        )
                        SELECT ROUND(AVG(pico), 1) AS media,
                               ROUND(MAX(pico), 1) AS peor,
                               ROUND(MIN(pico), 1) AS mejor,
                               COUNT(*) AS tiendas,
                               COUNT(*) FILTER (WHERE pico > 2 * (SELECT AVG(pico)
                                                                  FROM tienda)) AS malas
                        FROM tienda""",
                    corpo=lambda r: paragrafos(
                        "LA MEDIA ESCONDE LAS TIENDAS",
                        f"En hora punta, de media {pct(r[0]['media'])} de los pedidos "
                        f"salen fuera de los cuatro minutos, en {r[0]['tiendas']} tiendas.",
                        f"Pero la peor falla en {pct(r[0]['peor'])} y la mejor en "
                        f"{pct(r[0]['mejor'])}. {r[0]['malas']} están por encima del doble "
                        "de la media — y la media es justo el número que no le dice "
                        "cuáles.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "Por qué cuatro minutos",
                    "terco1b",
                    "servicio",
                    f"""SELECT ROUND(AVG(o.service_sec)) AS medio,
                               COUNT(*) AS pedidos,
                               COUNT(*) FILTER (WHERE o.service_sec > {_PRAZO}) AS fuera
                        FROM service.orders o""",
                    corpo=lambda r: paragrafos(
                        "EL UMBRAL, Y DE DÓNDE SALE",
                        f"Cuatro minutos del pedido a la entrega. El medio de la red es "
                        f"{r[0]['medio']} segundos sobre {n(r[0]['pedidos'])} pedidos.",
                        f"{n(r[0]['fuera'])} lo pasan. No es un objetivo inventado: es el "
                        "punto en que el cliente de mostrador empieza a mirar el reloj.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Dónde está bien",
                    "terco1c",
                    "tiendas",
                    f"""SELECT s.name AS tienda, s.format AS formato, s.city AS ciudad,
                               ROUND(100.0 * COUNT(*) FILTER (
                                     WHERE o.service_sec > {_PRAZO}
                                           AND o.day_part IN {_PICO})
                                     / NULLIF(COUNT(*) FILTER (
                                       WHERE o.day_part IN {_PICO}), 0), 1) AS pico
                        FROM service.orders o
                        JOIN restaurant.stores s ON s.id = o.store_id
                        GROUP BY s.id, s.name, s.format, s.city
                        ORDER BY 4 LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "LA QUE LO HACE BIEN",
                        f"{r[0]['tienda']} ({r[0]['formato']}, {r[0]['ciudad']}): solo "
                        f"{pct(r[0]['pico'])} fuera de plazo en hora punta.",
                        "La misma carta, la misma cocina y el mismo umbral. Lo que cambia "
                        "es el turno — y eso se puede copiar.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Fuera de plazo por franja",
                    "esq3",
                    "servicio",
                    SQL_SERVICO_POR_FAIXA,
                    variante="column",
                    x="day_part",
                    y="pct_over",
                ),
                grafico(
                    "Tiempo medio por canal",
                    "dir3",
                    "servicio",
                    """SELECT o.channel AS canal, ROUND(AVG(o.service_sec)) AS segundos
                       FROM service.orders o
                       GROUP BY o.channel ORDER BY segundos DESC""",
                    variante="bar",
                    x="canal",
                    y="segundos",
                ),
                tabela(
                    "Hora punta por tienda y franja",
                    "larga4",
                    "servicio",
                    f"""SELECT s.name AS "Tienda",
                               o.day_part AS "Franja",
                               COUNT(*) AS "Pedidos",
                               ROUND(AVG(o.service_sec)) AS "Medio (s)",
                               ROUND(100.0 * COUNT(*) FILTER (
                                     WHERE o.service_sec > {_PRAZO}) / COUNT(*), 1)
                                 AS "Fuera de plazo (%)",
                               ROUND(AVG(o.total), 2) AS "Ticket (€)"
                        FROM service.orders o
                        JOIN restaurant.stores s ON s.id = o.store_id
                        WHERE o.day_part IN {_PICO}
                        GROUP BY s.id, s.name, o.day_part
                        ORDER BY 5 DESC""",
                ),
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
                kpi(
                    "Personal sobre ventas",
                    "kpi1",
                    "tiendas",
                    V["pessoal_pct"],
                    legenda="En toda la red y el periodo",
                    formato="percent",
                ),
                kpi(
                    "Coste de personal",
                    "kpi2",
                    "tiendas",
                    V["pessoal_total"],
                    legenda="90 días, 12 tiendas",
                    formato="currency",
                ),
                kpi(
                    "La franja más cara",
                    "kpi3",
                    "tiendas",
                    V["faixa_mais_cara"],
                    legenda="Por euro de personal sobre euro vendido",
                ),
                kpi(
                    "La más rentable",
                    "kpi4",
                    "tiendas",
                    V["faixa_mais_barata"],
                    legenda="Donde la hora se paga sola",
                ),
                tabela("Ventas y personal por franja", "esq1", "tiendas", SQL_PESSOAL),
                grafico(
                    "Personal sobre ventas, por franja",
                    "dir1",
                    "tiendas",
                    SQL_SERIE_PESSOAL,
                    variante="bar",
                    x="t",
                    y="v",
                ),
                texto(
                    "Al revés de lo que dice el instinto",
                    "terco1a",
                    "tiendas",
                    """WITH v AS (
                           SELECT day_part, SUM(total) AS vendas
                           FROM service.orders GROUP BY day_part
                       ), p AS (
                           SELECT day_part, SUM(hours * cost_per_hour) AS custo
                           FROM restaurant.staff_shifts GROUP BY day_part
                       ), f AS (
                           SELECT v.day_part,
                                  100.0 * p.custo / NULLIF(v.vendas, 0) AS pct
                           FROM v JOIN p USING (day_part)
                       )
                       SELECT (SELECT day_part FROM f ORDER BY pct DESC LIMIT 1) AS cara,
                              (SELECT ROUND(pct, 1) FROM f ORDER BY pct DESC LIMIT 1)
                                AS cara_pct,
                              (SELECT day_part FROM f ORDER BY pct LIMIT 1) AS barata,
                              (SELECT ROUND(pct, 1) FROM f ORDER BY pct LIMIT 1)
                                AS barata_pct
                       FROM f LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "EL COSTE NO ESTÁ EN LA HORA PUNTA",
                        f"El personal pesa {pct(r[0]['cara_pct'])} de las ventas en "
                        f"{r[0]['cara']} y {pct(r[0]['barata_pct'])} en "
                        f"{r[0]['barata']}.",
                        "Al revés de lo que dice el instinto: la hora punta llena la "
                        "tienda y paga las horas. El coste está en las franjas vacías, "
                        "donde el turno sigue abierto.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "Qué se está midiendo",
                    "terco1b",
                    "tiendas",
                    """SELECT ROUND(SUM(hours)) AS horas,
                              ROUND(SUM(hours * cost_per_hour)) AS coste,
                              ROUND(AVG(cost_per_hour), 2) AS por_hora,
                              COUNT(DISTINCT store_id) AS tiendas
                       FROM restaurant.staff_shifts""",
                    corpo=lambda r: paragrafos(
                        "LA CUENTA, EN CLARO",
                        f"{n(r[0]['horas'])} horas trabajadas en {r[0]['tiendas']} "
                        f"tiendas, {eur(r[0]['coste'])} de coste, a "
                        f"{euro2(r[0]['por_hora'])} la hora de media.",
                        "Horas por turno multiplicadas por el coste de esa hora. No es la "
                        "nómina: son las horas que alguien decidió abrir.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Lo que se puede mover",
                    "terco1c",
                    "tiendas",
                    """WITH v AS (
                           SELECT day_part, SUM(total) AS vendas
                           FROM service.orders GROUP BY day_part
                       ), p AS (
                           SELECT day_part, SUM(hours * cost_per_hour) AS custo,
                                  SUM(hours) AS horas
                           FROM restaurant.staff_shifts GROUP BY day_part
                       )
                       SELECT v.day_part AS franja,
                              ROUND(p.horas) AS horas,
                              ROUND(p.custo) AS coste,
                              ROUND(100.0 * p.custo / NULLIF(v.vendas, 0), 1) AS pct
                       FROM v JOIN p USING (day_part)
                       ORDER BY p.custo / NULLIF(v.vendas, 0) DESC LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "DÓNDE ESTÁ LA DECISIÓN",
                        f"{r[0]['franja']}: {n(r[0]['horas'])} horas y "
                        f"{eur(r[0]['coste'])}, que son {pct(r[0]['pct'])} de lo que esa "
                        "franja vende.",
                        "No se trata de cerrar: se trata de cuántas personas están en la "
                        "tienda a esa hora. Es la decisión más barata de esta página.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Horas de personal por tienda",
                    "esq2",
                    "tiendas",
                    """SELECT s.name AS tienda, ROUND(SUM(sh.hours)) AS horas
                       FROM restaurant.staff_shifts sh
                       JOIN restaurant.stores s ON s.id = sh.store_id
                       GROUP BY s.id, s.name ORDER BY horas DESC""",
                    variante="bar",
                    x="tienda",
                    y="horas",
                ),
                grafico(
                    "Reparto del coste por franja",
                    "dir2",
                    "tiendas",
                    """SELECT day_part AS franja,
                              ROUND(SUM(hours * cost_per_hour)) AS coste
                       FROM restaurant.staff_shifts
                       GROUP BY day_part ORDER BY coste DESC""",
                    variante="pie",
                    x="franja",
                    y="coste",
                ),
                tabela(
                    "Personal sobre ventas, por tienda",
                    "larga3",
                    "tiendas",
                    """WITH v AS (
                           SELECT store_id, SUM(total) AS vendas, COUNT(*) AS pedidos
                           FROM service.orders GROUP BY store_id
                       ), p AS (
                           SELECT store_id, SUM(hours) AS horas,
                                  SUM(hours * cost_per_hour) AS custo
                           FROM restaurant.staff_shifts GROUP BY store_id
                       )
                       SELECT s.name AS "Tienda",
                              s.format AS "Formato",
                              s.seats AS "Plazas",
                              v.pedidos AS "Pedidos",
                              ROUND(v.vendas) AS "Ventas (€)",
                              ROUND(p.horas) AS "Horas",
                              ROUND(100.0 * p.custo / NULLIF(v.vendas, 0), 1)
                                AS "Personal/ventas (%)"
                       FROM restaurant.stores s
                       JOIN v ON v.store_id = s.id
                       JOIN p ON p.store_id = s.id
                       ORDER BY 7 DESC""",
                ),
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
                kpi(
                    "Merma en el periodo",
                    "kpi1",
                    "cocina",
                    V["merma_total"],
                    legenda="A coste, no a precio de carta",
                    formato="currency",
                ),
                kpi(
                    "Por caducidad",
                    "kpi2",
                    "cocina",
                    V["merma_validade"],
                    legenda="Producto con vida corta — es de carta",
                    formato="currency",
                ),
                kpi(
                    "Por preparar de más",
                    "kpi3",
                    "cocina",
                    V["merma_excesso"],
                    legenda="Se preparó para una ola que no vino",
                    formato="currency",
                ),
                kpi(
                    "La familia más perdida",
                    "kpi4",
                    "cocina",
                    V["familia_mais_perdida"],
                    legenda="Por coste tirado",
                ),
                tabela("Merma por artículo y motivo", "esq1", "cocina", SQL_MERMA),
                grafico(
                    "Merma por motivo",
                    "dir1",
                    "cocina",
                    SQL_SERIE_MERMA,
                    variante="bar",
                    x="t",
                    y="v",
                ),
                texto(
                    "Dos problemas, no uno",
                    "terco1a",
                    "cocina",
                    """SELECT ROUND(SUM(w.units * p.unit_cost)) AS total,
                              ROUND(SUM(w.units * p.unit_cost)
                                    FILTER (WHERE w.reason = 'caducidad')) AS caduca,
                              ROUND(SUM(w.units * p.unit_cost)
                                    FILTER (WHERE w.reason = 'preparado de más'))
                                AS exceso
                       FROM kitchen.waste w
                       JOIN kitchen.products p ON p.id = w.product_id""",
                    corpo=lambda r: paragrafos(
                        "LA MISMA LÍNEA, DOS CAUSAS",
                        f"{eur(r[0]['total'])} tirados: {eur(r[0]['caduca'])} por "
                        f"caducidad y {eur(r[0]['exceso'])} por preparar de más.",
                        "La caducidad es un problema de CARTA — producto con vida corta. "
                        "El exceso es de PREVISIÓN. En una hoja de turno son la misma "
                        "línea, y por eso se intenta arreglar con la misma orden.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "La vida del producto",
                    "terco1b",
                    "cocina",
                    """SELECT ROUND(AVG(p.hold_minutes)) AS medio,
                              MIN(p.hold_minutes) AS min_hold,
                              MAX(p.hold_minutes) AS max_hold,
                              COUNT(*) AS articulos
                       FROM kitchen.products p""",
                    corpo=lambda r: paragrafos(
                        "POR QUÉ CADUCA LO QUE CADUCA",
                        f"De los {r[0]['articulos']} artículos de carta, el tiempo de "
                        f"mantenimiento va de {r[0]['min_hold']} a {r[0]['max_hold']} "
                        f"minutos, con una media de {r[0]['medio']}.",
                        "Un artículo de 10 minutos y otro de 120 no se gestionan igual, y "
                        "la hoja de merma no distingue.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Dónde se corrige",
                    "terco1c",
                    "cocina",
                    """SELECT w.day_part AS franja,
                              ROUND(SUM(w.units * p.unit_cost)) AS coste,
                              SUM(w.units) AS unidades
                       FROM kitchen.waste w
                       JOIN kitchen.products p ON p.id = w.product_id
                       WHERE w.reason = 'preparado de más'
                       GROUP BY w.day_part ORDER BY 2 DESC LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "LA FRANJA QUE PREPARA DE MÁS",
                        f"{r[0]['franja']}: {eur(r[0]['coste'])} en "
                        f"{n(r[0]['unidades'])} unidades preparadas para una ola que no "
                        "vino.",
                        "Esta sí se corrige sin tocar la carta: es una previsión, y una "
                        "previsión se puede vigilar todos los días.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Merma por familia",
                    "esq2",
                    "cocina",
                    """SELECT p.family AS familia,
                              ROUND(SUM(w.units * p.unit_cost)) AS coste
                       FROM kitchen.waste w
                       JOIN kitchen.products p ON p.id = w.product_id
                       GROUP BY p.family ORDER BY coste DESC""",
                    variante="column",
                    x="familia",
                    y="coste",
                ),
                grafico(
                    "Merma semana a semana",
                    "dir2",
                    "cocina",
                    """SELECT TO_CHAR(DATE_TRUNC('week', w.wasted_on), 'YYYY-MM-DD')
                                AS semana,
                              ROUND(SUM(w.units * p.unit_cost)) AS coste
                       FROM kitchen.waste w
                       JOIN kitchen.products p ON p.id = w.product_id
                       GROUP BY 1 ORDER BY 1""",
                    variante="area",
                    x="semana",
                    y="coste",
                ),
                tabela(
                    "Merma por tienda y motivo",
                    "larga3",
                    "cocina",
                    """SELECT s.name AS "Tienda",
                              SUM(w.units) AS "Unidades",
                              ROUND(SUM(w.units * p.unit_cost)) AS "Coste (€)",
                              ROUND(SUM(w.units * p.unit_cost)
                                    FILTER (WHERE w.reason = 'caducidad'))
                                AS "Caducidad (€)",
                              ROUND(SUM(w.units * p.unit_cost)
                                    FILTER (WHERE w.reason = 'preparado de más'))
                                AS "Exceso (€)",
                              ROUND(SUM(w.units * p.unit_cost)
                                    FILTER (WHERE w.reason = 'error de pedido'))
                                AS "Error (€)"
                       FROM kitchen.waste w
                       JOIN kitchen.products p ON p.id = w.product_id
                       JOIN restaurant.stores s ON s.id = w.store_id
                       GROUP BY s.id, s.name ORDER BY 3 DESC""",
                ),
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
                kpi("Pedidos servidos", "kpi1", "servicio", V["pedidos"], legenda="90 días"),
                kpi(
                    "Ticket medio",
                    "kpi2",
                    "servicio",
                    V["ticket_medio"],
                    legenda="Importe medio por pedido",
                    formato="currency",
                ),
                kpi(
                    "El canal que más vende",
                    "kpi3",
                    "servicio",
                    V["canal_maior"],
                    legenda="Por importe, no por número",
                ),
                kpi(
                    "Margen medio de carta",
                    "kpi4",
                    "cocina",
                    V["margem_carta"],
                    legenda="Precio contra coste, por artículo",
                    formato="percent",
                ),
                grafico(
                    "Ventas por canal",
                    "esq1",
                    "servicio",
                    SQL_CANAL,
                    variante="bar",
                    x="channel",
                    y="sales",
                ),
                tabela("Margen por familia de carta", "dir1", "cocina", SQL_CARTA),
                texto(
                    "Importe y ticket no son el mismo canal",
                    "terco1a",
                    "servicio",
                    """SELECT (SELECT channel FROM service.orders
                                 GROUP BY channel ORDER BY SUM(total) DESC LIMIT 1)
                                AS mas_importe,
                              (SELECT channel FROM service.orders
                                 GROUP BY channel ORDER BY AVG(total) DESC LIMIT 1)
                                AS mas_ticket,
                              (SELECT ROUND(AVG(total), 2) FROM service.orders
                                 GROUP BY channel ORDER BY AVG(total) DESC LIMIT 1)
                                AS ticket_alto,
                              (SELECT ROUND(AVG(total), 2) FROM service.orders
                                 GROUP BY channel ORDER BY AVG(total) LIMIT 1)
                                AS ticket_bajo""",
                    corpo=lambda r: paragrafos(
                        "DOS CANALES DISTINTOS",
                        f"El que más importe trae es {r[0]['mas_importe']}. El del ticket "
                        f"más alto es {r[0]['mas_ticket']}, a "
                        f"{euro2(r[0]['ticket_alto'])} frente a "
                        f"{euro2(r[0]['ticket_bajo'])} del último.",
                        "Uno llena la caja y el otro sube la cuenta. Empujar el primero "
                        "sin mirar el segundo es trabajar más por lo mismo.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "Qué sostiene el margen",
                    "terco1b",
                    "cocina",
                    """SELECT (SELECT family FROM kitchen.products GROUP BY family
                                ORDER BY AVG((menu_price - unit_cost)
                                             / NULLIF(menu_price, 0)) DESC LIMIT 1)
                                AS mejor,
                              (SELECT ROUND(100.0 * AVG((menu_price - unit_cost)
                                            / NULLIF(menu_price, 0)), 1)
                                 FROM kitchen.products GROUP BY family
                                 ORDER BY AVG((menu_price - unit_cost)
                                              / NULLIF(menu_price, 0)) DESC LIMIT 1)
                                AS mejor_pct,
                              (SELECT family FROM kitchen.products GROUP BY family
                                 ORDER BY AVG((menu_price - unit_cost)
                                              / NULLIF(menu_price, 0)) LIMIT 1)
                                AS peor,
                              (SELECT ROUND(100.0 * AVG((menu_price - unit_cost)
                                            / NULLIF(menu_price, 0)), 1)
                                 FROM kitchen.products GROUP BY family
                                 ORDER BY AVG((menu_price - unit_cost)
                                              / NULLIF(menu_price, 0)) LIMIT 1)
                                AS peor_pct""",
                    corpo=lambda r: paragrafos(
                        "LAS FAMILIAS QUE PAGAN LA CARTA",
                        f"{r[0]['mejor']} deja {pct(r[0]['mejor_pct'])} de margen; "
                        f"{r[0]['peor']}, {pct(r[0]['peor_pct'])}.",
                        "Las dos están en la misma carta y al mismo precio de menú. La "
                        "diferencia es el coste del producto — y es ahí donde se decide "
                        "qué se promociona.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Lo que se puede empujar",
                    "terco1c",
                    "servicio",
                    """SELECT o.channel AS canal,
                              COUNT(*) AS pedidos,
                              ROUND(AVG(o.total), 2) AS ticket,
                              ROUND(AVG(o.service_sec)) AS segundos
                       FROM service.orders o
                       GROUP BY o.channel
                       ORDER BY AVG(o.total) DESC LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "POR DÓNDE CRECER",
                        f"{r[0]['canal']}: {euro2(r[0]['ticket'])} de ticket medio en "
                        f"{n(r[0]['pedidos'])} pedidos, servidos en "
                        f"{r[0]['segundos']} segundos de media.",
                        "Es el canal con el ticket más alto. Cada pedido que se mueve "
                        "hacia aquí vale más sin costar una hora más de cocina.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Ticket medio por canal",
                    "esq2",
                    "servicio",
                    """SELECT o.channel AS canal, ROUND(AVG(o.total), 2) AS ticket
                       FROM service.orders o
                       GROUP BY o.channel ORDER BY ticket DESC""",
                    variante="column",
                    x="canal",
                    y="ticket",
                ),
                grafico(
                    "Reparto de pedidos por canal",
                    "dir2",
                    "servicio",
                    """SELECT o.channel AS canal, COUNT(*) AS pedidos
                       FROM service.orders o
                       GROUP BY o.channel ORDER BY pedidos DESC""",
                    variante="pie",
                    x="canal",
                    y="pedidos",
                ),
                tabela(
                    "Lo que más se vende, y lo que deja",
                    "larga3",
                    "cocina",
                    """SELECT p.name AS "Artículo",
                              p.family AS "Familia",
                              SUM(oi.quantity) AS "Unidades",
                              ROUND(SUM(oi.quantity * oi.unit_price)) AS "Ventas (€)",
                              ROUND(p.menu_price, 2) AS "Precio (€)",
                              ROUND(p.unit_cost, 2) AS "Coste (€)",
                              ROUND(100.0 * (p.menu_price - p.unit_cost)
                                    / NULLIF(p.menu_price, 0), 1) AS "Margen (%)"
                       FROM service.order_items oi
                       JOIN kitchen.products p ON p.id = oi.product_id
                       GROUP BY p.id, p.name, p.family, p.menu_price, p.unit_cost
                       ORDER BY 4 DESC LIMIT 40""",
                ),
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


# ── as perguntas ─────────────────────────────────────────────────────
#
# Cinco fios já respondidos. A resposta é construída a partir do
# resultado da consulta, não escrita à mão — ver a nota longa em
# `pecas.Pergunta`. O que está escrito é a *forma* da resposta: o que
# vale a pena dizer e em que ordem.
#
# Em castelhano, e com os números no formato europeu, que é o que a
# aplicação mostra nos cartões ao lado.


def _r_servico(linhas):
    if not linhas:
        return "No hay pedidos en el periodo."
    lentas = [r for r in linhas if float(r["pct_over_peak"] or 0) > 40]
    resto = [r for r in linhas if float(r["pct_over_peak"] or 0) <= 40]
    media_resto = sum(float(r["pct_over_peak"] or 0) for r in resto) / len(resto) if resto else 0
    cabeca = ", ".join(f"{r['store']} ({pct(r['pct_over_peak'])})" for r in lentas) or "ninguna"
    return (
        f"En hora punta el incumplimiento se concentra en {len(lentas)} de "
        f"{len(linhas)} tiendas: {cabeca}. Las demás se quedan en torno al "
        f"{pct(media_resto)}.\n\n"
        "La media de la red no sirve para decidir aquí: mezclar esas dos con "
        "las demás da un número que no manda a nadie a ningún sitio. Y son "
        "lentas **en hora punta**, no siempre — su media fuera del pico se "
        "parece a la del resto, así que no es el equipo, es lo que pasa "
        "cuando la casa se llena."
    )


def _r_pessoal(linhas):
    if not linhas:
        return "No hay turnos registrados en el periodo."
    cara, barata = linhas[0], linhas[-1]
    return (
        f"El personal pesa {pct(cara['labour_pct'])} de las ventas en "
        f"**{cara['day_part']}** y {pct(barata['labour_pct'])} en "
        f"**{barata['day_part']}**.\n\n"
        f"Es al revés de lo que dice el instinto. En {barata['day_part']} hay "
        f"{n(barata['hours'])} horas para {eur(barata['sales'])} de ventas; "
        f"en {cara['day_part']}, {n(cara['hours'])} horas para "
        f"{eur(cara['sales'])}. El coste no está en la hora punta — está en "
        "las franjas vacías, donde la plantilla sigue puesta y la caja no."
    )


def _r_merma(linhas):
    if not linhas:
        return "No hay merma registrada en el periodo."
    por_motivo: dict[str, float] = {}
    for r in linhas:
        por_motivo[r["reason"]] = por_motivo.get(r["reason"], 0) + float(r["cost"] or 0)

    ordenado = sorted(por_motivo.items(), key=lambda x: -x[1])
    linhas_motivo = "\n".join(f"- {m}: {eur(v)}" for m, v in ordenado)
    topo = linhas[0]
    return (
        f"{linhas_motivo}\n\n"
        f"El artículo que más cuesta es **{topo['product']}** "
        f"({topo['family']}, {eur(topo['cost'])}, vida de "
        f"{n(topo['hold_minutes'])} minutos).\n\n"
        "La separación importa: la caducidad se corrige en la carta — un "
        "producto con vida de diez minutos tira solo —, y el exceso de "
        "preparación se corrige en la previsión del turno. En una hoja de "
        "turno son la misma línea, y por eso nadie arregla ninguna de las dos."
    )


def _r_canal(linhas):
    if not linhas:
        return "No hay pedidos en el periodo."
    por_importe = linhas[0]
    por_ticket = max(linhas, key=lambda r: float(r["avg_ticket"] or 0))
    detalhe = "\n".join(
        f"- {r['channel']}: {n(r['orders'])} pedidos, {eur(r['sales'])}, "
        f"ticket {euro2(r['avg_ticket'])}, "
        f"{n(r['avg_sec'])} s de media"
        for r in linhas
    )
    return (
        f"{detalhe}\n\n"
        f"**{por_importe['channel']}** trae el importe; "
        f"**{por_ticket['channel']}** trae el ticket más alto. No son "
        "necesariamente el mismo, y confundirlos lleva a empujar el canal "
        "equivocado: el que hace volumen no es el que sube la caja por pedido."
    )


def _r_carta(linhas):
    if not linhas:
        return "No hay artículos en la carta."
    pior, melhor = linhas[0], linhas[-1]
    detalhe = "\n".join(
        f"- {r['family']}: margen {pct(r['margin_pct'])}, " f"vida {n(r['hold_min'])} min"
        for r in linhas
    )
    return (
        f"{detalhe}\n\n"
        f"**{pior['family']}** es la familia de margen más bajo "
        f"({pct(pior['margin_pct'])}) y **{melhor['family']}** la más alta "
        f"({pct(melhor['margin_pct'])}).\n\n"
        "Lo que hay que mirar es el cruce con la vida del producto: margen "
        "bajo con caducidad corta es la peor combinación que existe — se gana "
        "poco por unidad y se tira lo que no se vende en minutos."
    )


# ── o vocabulário desta casa ────────────────────────────────────────
#
# A IA lê isto. «Merma» e «hora punta» são as palavras da casa, e as
# fórmulas são as MESMAS dos widgets.

METRICAS = [
    Metrica(
        "Tiempo de servicio",
        "Segundos entre el pedido y la entrega. El umbral de la casa son "
        "cuatro minutos: el punto en que el cliente de mostrador empieza "
        "a mirar el reloj.",
        "SELECT AVG(o.service_sec) FROM service.orders o",
        unidade="s",
        agregacao="avg",
    ),
    Metrica(
        "Fuera de plazo en hora punta",
        "Pedidos que pasan de los cuatro minutos en comida y cena, sobre "
        "el total de esas franjas.",
        f"""SELECT 100.0 * COUNT(*) FILTER (
                   WHERE o.service_sec > {_PRAZO} AND o.day_part IN {_PICO})
                 / NULLIF(COUNT(*) FILTER (WHERE o.day_part IN {_PICO}), 0)
            FROM service.orders o""",
        unidade="%",
        agregacao="ratio",
    ),
    Metrica(
        "Personal sobre ventas",
        "Coste de las horas trabajadas por cada euro vendido. El coste no "
        "está en la hora punta: está en las franjas vacías.",
        """WITH v AS (SELECT SUM(total) AS vendas FROM service.orders),
                p AS (SELECT SUM(hours * cost_per_hour) AS custo
                      FROM restaurant.staff_shifts)
           SELECT 100.0 * p.custo / NULLIF(v.vendas, 0) FROM v, p""",
        unidade="%",
        agregacao="ratio",
    ),
    Metrica(
        "Merma",
        "Coste del producto preparado que acaba en la basura, valorado a "
        "coste de materia prima y no a precio de carta — es lo que se "
        "perdió, no lo que se dejó de ganar.",
        """SELECT SUM(w.units * p.unit_cost)
           FROM kitchen.waste w
           JOIN kitchen.products p ON p.id = w.product_id""",
        unidade="EUR",
        agregacao="sum",
    ),
    Metrica(
        "Ticket medio",
        "Importe medio por pedido servido, sumando todas las líneas. Sube "
        "con la venta cruzada y con la carta, no con el número de "
        "pedidos — por eso se mira al lado del canal.",
        "SELECT AVG(o.total) FROM service.orders o",
        unidade="EUR",
        agregacao="avg",
    ),
]

GLOSSARIO = [
    Termo(
        "Merma",
        "Producto preparado que se tira. Son DOS problemas en la misma "
        "línea: por caducidad (es de carta, producto de vida corta) o por "
        "preparar de más (es de previsión). Se intentan arreglar con la "
        "misma orden y no se arregla ninguno.",
        ["desperdicio", "producto tirado"],
    ),
    Termo(
        "Hora punta",
        "Las franjas de comida y cena. Es cuando la tienda está llena — y "
        "es también cuando el personal se paga solo, al revés de lo que "
        "dice el instinto.",
        ["pico", "comida y cena"],
    ),
    Termo(
        "Tiempo de mantenimiento",
        "Minutos que un artículo aguanta preparado antes de dejar de "
        "servirse. Va de diez minutos a dos horas según el producto, y la "
        "hoja de merma no distingue.",
        ["hold", "vida en mostrador"],
    ),
    Termo(
        "Franja",
        "El tramo del día: desayuno, comida, tarde, cena, noche. Es la "
        "unidad en la que se decide cuánta gente está en la tienda.",
        ["day part", "turno"],
    ),
]


SECTOR.metricas = METRICAS
SECTOR.glossario = GLOSSARIO

SECTOR.perguntas = [
    Pergunta(
        texto="¿En qué tiendas se nos va el tiempo de servicio en hora punta?",
        esquemas=["servicio", "tiendas"],
        sql=SQL_SERVICO_POR_LOJA,
        pagina="Velocidad de servicio",
        resposta=_r_servico,
    ),
    Pergunta(
        texto="¿Cuánto me cuesta la hora de personal por cada euro que vendo?",
        esquemas=["tiendas", "servicio"],
        sql=SQL_PESSOAL,
        pagina="Coste de personal",
        resposta=_r_pessoal,
    ),
    Pergunta(
        texto="¿Qué estamos tirando, y es por caducidad o por preparar de más?",
        esquemas=["cocina"],
        sql=SQL_MERMA,
        pagina="Merma",
        resposta=_r_merma,
    ),
    Pergunta(
        texto="¿Qué canal trae el importe y cuál trae el ticket?",
        esquemas=["servicio"],
        sql=SQL_CANAL,
        pagina="Canal y carta",
        resposta=_r_canal,
    ),
    Pergunta(
        texto="¿Qué familias de la carta sostienen el margen?",
        esquemas=["cocina"],
        sql=SQL_CARTA,
        pagina="Canal y carta",
        resposta=_r_carta,
    ),
]
