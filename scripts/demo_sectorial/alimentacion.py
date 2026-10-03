# -*- coding: utf-8 -*-
"""Demonstração sectorial — Alimentação Selecta e Vinhos, em castelhano.

Para a distribuição alimentar e de vinhos a hostelaria — o perfil da
Representaciones Barrero, em Badajoz. Já existe um sector de
Distribuição genérico, e não chega: aqui a mercadoria morre, o preço
não é o preço, e o stock parado às vezes é estratégia.

Dados em `scripts/demo/seed_food.sql`. Sintéticos, de ninguém.

── As três perguntas ───────────────────────────────────────────────

1. **O que caduca, e quanto vale.** O stock vê-se por referência; a
   validade está no lote. São duas vistas da mesma mercadoria e só uma
   delas sabe a data. A diferença entre o que já caducou e o que caduca
   nos próximos 60 dias é a diferença entre uma perda e uma campanha.

2. **A margem depois do rappel.** O desconto acordado aplica-se sobre o
   acumulado, no fim, e não aparece em nenhuma linha de factura. A
   margem bruta é igual em todos os canais; a líquida não é.

3. **O capital parado, separado por motivo.** O vinho de guarda está
   parado porque deve estar. O resto está parado porque alguém se
   esqueceu. Numa folha de stock os dois são a mesma linha.

── Três ligações, e porquê estas ───────────────────────────────────

Uma ligação Postgres vê um esquema só. A divisão foi feita para que a
pergunta que mais vale — a da caducidade — caiba inteira dentro de uma:
os lotes vivem no armazém com as existências, não no catálogo.

Como no sector dos transportes, as junções entre esquemas ficam nos
painéis (pré-calculadas) e os agentes ficam com perguntas de um esquema
só, que é o que lhes permite correr ao vivo sem mentir.
"""

from __future__ import annotations

from scripts.demo_sectorial.pecas import Agente, Pagina, Sector, grafico, kpi, tabela

# ── blocos reutilizados ─────────────────────────────────────────────

# O que está em armazém, com a validade e o custo ao lado. O
# `NOT p.is_vintage` tira o vinho de guarda: ele não "caduca", envelhece,
# e metê-lo nesta conta inventava um problema que não existe.
_CADUCA = """FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0 AND NOT p.is_vintage"""

# A margem, com e sem o rappel do contrato.
_MARGEM = """FROM trade.order_lines ol
JOIN trade.orders o ON o.id = ol.order_id
JOIN trade.customers c ON c.id = o.customer_id
JOIN warehouse.lots l ON l.id = ol.lot_id
JOIN assortment.products p ON p.id = l.product_id"""

_NETO = "ol.quantity * (ol.unit_price * (1 - ol.discount) * (1 - c.rebate_pct) - p.unit_cost)"
_BRUTO = "ol.quantity * (ol.unit_price * (1 - ol.discount) - p.unit_cost)"
_VENDA = "ol.quantity * ol.unit_price * (1 - ol.discount)"


SECTOR = Sector(
    chave="alimentacion",
    nome_do_projecto="Alimentación Selecta y Vinos",
    descricao=(
        "Demostración sectorial: caducidades por lote, margen real después "
        "del rappel y capital parado en almacén."
    ),
    ligacoes={
        "catalogo": (
            "Catálogo",
            "assortment",
            "Referencias, familias y proveedores. El sistema que sabe lo que "
            "cuesta la mercancía y a cuánto se vende de tarifa.",
        ),
        "almacen": (
            "Almacén",
            "warehouse",
            "Lotes y existencias. El único sitio donde está la fecha de "
            "caducidad — y por eso el único que sabe lo que se va a perder.",
        ),
        "comercial": (
            "Comercial",
            "trade",
            "Clientes de hostelería, pedidos y el rappel acordado. El rappel "
            "está en el contrato, no en la factura.",
        ),
    },
    paginas=[
        # ─────────────────────────────────────────────────────────────
        Pagina(
            nome="Caducidad por lote",
            descricao=(
                "El stock se mira por referencia; la fecha está en el lote. "
                "La diferencia entre lo ya caducado y lo que caduca en 60 días "
                "es la diferencia entre una pérdida y una campaña."
            ),
            icone="calendar",
            cor="#E05C5C",
            widgets=[
                kpi(
                    "Ya caducado en almacén", "kpi1", "almacen",
                    f"SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v "
                    f"{_CADUCA} AND l.best_before < CURRENT_DATE",
                    legenda="Mercancía con existencias y fecha pasada",
                    formato="currency",
                ),
                kpi(
                    "Caduca en 60 días", "kpi2", "almacen",
                    f"SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v "
                    f"{_CADUCA} AND l.best_before >= CURRENT_DATE "
                    "AND l.best_before < CURRENT_DATE + 60",
                    legenda="Esto todavía se vende — pero solo si se sabe",
                    formato="currency",
                ),
                kpi(
                    "Lotes afectados", "kpi3", "almacen",
                    f"SELECT COUNT(*) AS v {_CADUCA} "
                    "AND l.best_before < CURRENT_DATE + 60",
                    legenda="Entre caducados y a punto de caducar",
                ),
                kpi(
                    "La familia más expuesta", "kpi4", "catalogo",
                    f"SELECT p.family AS v {_CADUCA} "
                    "AND l.best_before < CURRENT_DATE + 60 "
                    "GROUP BY p.family ORDER BY SUM(s.quantity * p.unit_cost) DESC LIMIT 1",
                    legenda="Por valor en riesgo, no por número de lotes",
                ),
                tabela(
                    "Lotes a vigilar", "larga1", "almacen",
                    """SELECT l.lot_code AS "Lote",
                              p.name AS "Referencia",
                              p.family AS "Familia",
                              l.best_before AS "Caduca",
                              (l.best_before - CURRENT_DATE) AS "Días",
                              s.quantity AS "Unidades",
                              ROUND(s.quantity * p.unit_cost) AS "Coste (€)",
                              s.zone AS "Zona"
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0 AND NOT p.is_vintage
                         AND l.best_before < CURRENT_DATE + 60
                       ORDER BY l.best_before
                       LIMIT 60""",
                ),
                grafico(
                    "Valor en riesgo por familia", "larga2", "catalogo",
                    f"""SELECT p.family AS familia,
                               ROUND(SUM(s.quantity * p.unit_cost)) AS coste
                        {_CADUCA} AND l.best_before < CURRENT_DATE + 60
                        GROUP BY p.family ORDER BY coste DESC""",
                    variante="bar", x="familia", y="coste",
                ),
            ],
        ),
        # ─────────────────────────────────────────────────────────────
        Pagina(
            nome="Margen real",
            descricao=(
                "El rappel se aplica sobre el acumulado, al final, y no aparece "
                "en ninguna línea de factura. El margen bruto es casi igual en "
                "todos los canales. El neto no."
            ),
            icone="percent",
            cor="#F5A623",
            widgets=[
                kpi(
                    "Facturado en el periodo", "kpi1", "comercial",
                    f"SELECT COALESCE(ROUND(SUM({_VENDA})), 0) AS v {_MARGEM}",
                    legenda="18 meses de pedidos servidos", formato="currency",
                ),
                kpi(
                    "Margen bruto", "kpi2", "catalogo",
                    f"SELECT ROUND(100.0 * SUM({_BRUTO}) / NULLIF(SUM({_VENDA}), 0), 1) AS v "
                    f"{_MARGEM}",
                    legenda="El que se celebra en enero", formato="percent",
                ),
                kpi(
                    "Margen neto tras rappel", "kpi3", "comercial",
                    f"SELECT ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS v "
                    f"{_MARGEM}",
                    legenda="El que queda en diciembre", formato="percent",
                ),
                kpi(
                    "Lo que cuesta el rappel", "kpi4", "comercial",
                    f"SELECT COALESCE(ROUND(SUM({_BRUTO}) - SUM({_NETO})), 0) AS v {_MARGEM}",
                    legenda="Acordado en contrato, invisible en la factura",
                    formato="currency",
                ),
                grafico(
                    "Margen neto por canal", "esq1", "comercial",
                    f"""SELECT c.channel AS canal,
                               ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS neto
                        {_MARGEM} GROUP BY c.channel ORDER BY neto""",
                    variante="bar", x="canal", y="neto",
                ),
                tabela(
                    "Bruto contra neto, por canal", "dir1", "comercial",
                    f"""SELECT c.channel AS "Canal",
                               COUNT(DISTINCT o.id) AS "Pedidos",
                               ROUND(SUM({_VENDA})) AS "Facturado (€)",
                               ROUND(100.0 * SUM({_BRUTO}) / NULLIF(SUM({_VENDA}), 0), 1) AS "Bruto (%)",
                               ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS "Neto (%)",
                               ROUND(SUM({_BRUTO}) - SUM({_NETO})) AS "Rappel (€)"
                        {_MARGEM} GROUP BY c.channel ORDER BY 5""",
                ),
            ],
        ),
        # ─────────────────────────────────────────────────────────────
        Pagina(
            nome="Capital parado",
            descricao=(
                "El vino de guarda está parado porque debe estarlo. El resto "
                "está parado porque alguien se olvidó. En una hoja de stock "
                "los dos son la misma línea."
            ),
            icone="package",
            cor="#7B61FF",
            widgets=[
                kpi(
                    "Capital en almacén", "kpi1", "almacen",
                    """SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0""",
                    legenda="A coste, no a tarifa", formato="currency",
                ),
                kpi(
                    "De guarda — parado a propósito", "kpi2", "catalogo",
                    """SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0 AND p.is_vintage""",
                    legenda="Esto es estrategia, no descuido", formato="currency",
                ),
                kpi(
                    "Parado sin ser de guarda", "kpi3", "almacen",
                    """SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0 AND NOT p.is_vintage""",
                    legenda="Aquí es donde hay una conversación",
                    formato="currency",
                ),
                kpi(
                    "Referencias sin una sola venta", "kpi4", "catalogo",
                    """SELECT COUNT(*) AS v FROM assortment.products p
                       WHERE NOT EXISTS (
                           SELECT 1 FROM trade.order_lines ol
                           JOIN warehouse.lots l ON l.id = ol.lot_id
                           WHERE l.product_id = p.id)""",
                    legenda="Se compraron, se quedaron, nadie volvió a mirar",
                ),
                grafico(
                    "Capital parado por familia", "esq1", "catalogo",
                    """SELECT p.family AS familia,
                              ROUND(SUM(s.quantity * p.unit_cost)) AS capital
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0
                       GROUP BY p.family ORDER BY capital DESC""",
                    variante="bar", x="familia", y="capital",
                ),
                tabela(
                    "Las referencias más paradas", "dir1", "catalogo",
                    """SELECT p.sku AS "Referencia",
                              p.name AS "Nombre",
                              p.family AS "Familia",
                              CASE WHEN p.is_vintage THEN 'sí' ELSE 'no' END AS "De guarda",
                              SUM(s.quantity) AS "Unidades",
                              ROUND(SUM(s.quantity * p.unit_cost)) AS "Capital (€)"
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0
                       GROUP BY p.id, p.sku, p.name, p.family, p.is_vintage
                       ORDER BY 6 DESC LIMIT 40""",
                ),
            ],
        ),
        # ─────────────────────────────────────────────────────────────
        Pagina(
            nome="Clientes y plaza",
            descricao=(
                "Quién compra, dónde, y cuánto deja de verdad. La plaza que "
                "más factura no es siempre la que más deja."
            ),
            icone="users",
            cor="#4A90D9",
            widgets=[
                kpi(
                    "La plaza que más factura", "kpi1", "comercial",
                    f"""SELECT c.city AS v {_MARGEM}
                        GROUP BY c.city ORDER BY SUM({_VENDA}) DESC LIMIT 1""",
                    legenda="Por importe servido",
                ),
                kpi(
                    "El canal que más deja", "kpi2", "comercial",
                    f"""SELECT c.channel AS v {_MARGEM}
                        GROUP BY c.channel
                        ORDER BY SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0) DESC LIMIT 1""",
                    legenda="Por margen neto, no por facturación",
                ),
                kpi(
                    "Pedidos servidos", "kpi3", "comercial",
                    "SELECT COUNT(*) AS v FROM trade.orders WHERE status = 'delivered'",
                    legenda="18 meses",
                ),
                kpi(
                    "Ticket medio", "kpi4", "comercial",
                    f"""SELECT ROUND(SUM({_VENDA}) / NULLIF(COUNT(DISTINCT o.id), 0)) AS v
                        {_MARGEM}""",
                    legenda="Importe medio por pedido servido", formato="currency",
                ),
                grafico(
                    "Facturación por plaza", "esq1", "comercial",
                    f"""SELECT c.city AS plaza, ROUND(SUM({_VENDA})) AS facturado
                        {_MARGEM} GROUP BY c.city ORDER BY facturado DESC""",
                    variante="bar", x="plaza", y="facturado",
                ),
                tabela(
                    "Los clientes que más pesan", "dir1", "comercial",
                    f"""SELECT c.name AS "Cliente",
                               c.channel AS "Canal",
                               c.city AS "Plaza",
                               COUNT(DISTINCT o.id) AS "Pedidos",
                               ROUND(SUM({_VENDA})) AS "Facturado (€)",
                               ROUND(100.0 * c.rebate_pct, 2) AS "Rappel (%)",
                               ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS "Neto (%)"
                        {_MARGEM}
                        GROUP BY c.id, c.name, c.channel, c.city, c.rebate_pct
                        ORDER BY 5 DESC LIMIT 40""",
                ),
            ],
        ),
    ],
    # ── os agentes ──────────────────────────────────────────────────
    #
    # Cada um dentro de um esquema. A pergunta da caducidade cabe no
    # armazém porque os lotes foram para lá de propósito.
    agentes=[
        Agente(
            nome="Lotes a punto de caducar",
            esquema="almacen",
            tabelas=["warehouse.lots", "warehouse.stock"],
            foco=(
                "Revisa los lotes con existencias cuya fecha de caducidad esté "
                "dentro de los próximos 60 días. Dime el código de lote, cuántas "
                "unidades quedan y cuántos días faltan, empezando por los más "
                "cercanos. Lo que caduca la semana que viene todavía se vende; "
                "lo que caducó ayer ya no."
            ),
            frequencia="daily",
            arquetipo="risk_radar",
        ),
        Agente(
            nome="Existencias sin salida",
            esquema="almacen",
            tabelas=["warehouse.lots", "warehouse.stock"],
            foco=(
                "Busca lotes que entraron hace mucho y siguen casi completos en "
                "almacén. Dime cuáles son, en qué zona están y qué porcentaje "
                "del lote original queda. Un lote que entró y no se movió es "
                "dinero en una estantería."
            ),
            frequencia="weekly",
            arquetipo="operations_monitor",
        ),
        Agente(
            nome="Margen de tarifa por familia",
            esquema="catalogo",
            tabelas=["assortment.products"],
            foco=(
                "Compara el precio de tarifa con el coste unitario de cada "
                "referencia y agrúpalo por familia. Avísame de las familias "
                "cuyo margen de tarifa esté por debajo del resto, y de las "
                "referencias concretas que tiran de ese número hacia abajo."
            ),
            frequencia="monthly",
            arquetipo="financial_analyst",
        ),
        Agente(
            nome="Rappel acumulado por cliente",
            esquema="comercial",
            tabelas=["trade.customers", "trade.orders", "trade.order_lines"],
            foco=(
                "Calcula lo facturado a cada cliente en el año y aplícale el "
                "rappel acordado para saber cuánto habrá que devolverle. "
                "Avísame de los clientes cuyo rappel acumulado esté creciendo "
                "más deprisa que su facturación: ese es el que sorprende en "
                "diciembre."
            ),
            frequencia="monthly",
            arquetipo="financial_analyst",
        ),
        Agente(
            nome="Clientes que bajan de pedido",
            esquema="comercial",
            tabelas=["trade.customers", "trade.orders", "trade.order_lines"],
            foco=(
                "Compara los pedidos de cada cliente en los últimos tres meses "
                "con los tres anteriores. Dime quién ha bajado de forma clara, "
                "en número de pedidos o en importe. En hostelería un cliente no "
                "avisa de que se va: deja de pedir."
            ),
            frequencia="weekly",
            arquetipo="growth_intelligence",
        ),
    ],
)
