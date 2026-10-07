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
                    "Ya caducado en almacén",
                    "kpi1",
                    "almacen",
                    f"SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v "
                    f"{_CADUCA} AND l.best_before < CURRENT_DATE",
                    legenda="Mercancía con existencias y fecha pasada",
                    formato="currency",
                ),
                kpi(
                    "Caduca en 60 días",
                    "kpi2",
                    "almacen",
                    f"SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v "
                    f"{_CADUCA} AND l.best_before >= CURRENT_DATE "
                    "AND l.best_before < CURRENT_DATE + 60",
                    legenda="Esto todavía se vende — pero solo si se sabe",
                    formato="currency",
                ),
                kpi(
                    "Lotes afectados",
                    "kpi3",
                    "almacen",
                    f"SELECT COUNT(*) AS v {_CADUCA} " "AND l.best_before < CURRENT_DATE + 60",
                    legenda="Entre caducados y a punto de caducar",
                ),
                kpi(
                    "La familia más expuesta",
                    "kpi4",
                    "catalogo",
                    f"SELECT p.family AS v {_CADUCA} "
                    "AND l.best_before < CURRENT_DATE + 60 "
                    "GROUP BY p.family ORDER BY SUM(s.quantity * p.unit_cost) DESC LIMIT 1",
                    legenda="Por valor en riesgo, no por número de lotes",
                ),
                tabela(
                    "Lotes a vigilar",
                    "larga1",
                    "almacen",
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
                    "Valor en riesgo por familia",
                    "larga2",
                    "catalogo",
                    f"""SELECT p.family AS familia,
                               ROUND(SUM(s.quantity * p.unit_cost)) AS coste
                        {_CADUCA} AND l.best_before < CURRENT_DATE + 60
                        GROUP BY p.family ORDER BY coste DESC""",
                    variante="bar",
                    x="familia",
                    y="coste",
                ),
                texto(
                    "Pérdida contra campaña",
                    "terco1a",
                    "almacen",
                    f"""SELECT ROUND(SUM(s.quantity * p.unit_cost)
                                     FILTER (WHERE l.best_before < CURRENT_DATE)) AS perdido,
                               ROUND(SUM(s.quantity * p.unit_cost)
                                     FILTER (WHERE l.best_before >= CURRENT_DATE
                                             AND l.best_before < CURRENT_DATE + 60))
                                 AS en_riesgo,
                               COUNT(*) FILTER (WHERE l.best_before >= CURRENT_DATE
                                                AND l.best_before < CURRENT_DATE + 60)
                                 AS lotes
                        {_CADUCA}""",
                    corpo=lambda r: paragrafos(
                        "PÉRDIDA O CAMPAÑA",
                        f"{eur(r[0]['perdido'])} ya caducado: eso es pérdida, y no hay "
                        "nada que hacer.",
                        f"{eur(r[0]['en_riesgo'])} en {n(r[0]['lotes'])} lotes caducan en "
                        "los próximos 60 días. Eso todavía es una campaña — pero solo si "
                        "alguien lo sabe con tiempo.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "El vino de guarda no cuenta",
                    "terco1b",
                    "catalogo",
                    """SELECT COUNT(*) FILTER (WHERE p.is_vintage) AS vintage,
                              COUNT(*) AS total
                       FROM assortment.products p""",
                    corpo=lambda r: paragrafos(
                        "LO QUE NO ENTRA EN ESTA CUENTA",
                        f"{r[0]['vintage']} de {r[0]['total']} referencias son de guarda. "
                        "No caducan: envejecen.",
                        "Meterlas aquí inventaría un problema que no existe — y es el "
                        "primer error que comete cualquier informe de caducidades hecho "
                        "con una fecha y nada más.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Dónde está el riesgo",
                    "terco1c",
                    "catalogo",
                    f"""SELECT p.family AS familia,
                               ROUND(SUM(s.quantity * p.unit_cost)) AS coste,
                               MIN(l.best_before - CURRENT_DATE) AS primeros_dias
                        {_CADUCA} AND l.best_before < CURRENT_DATE + 60
                        GROUP BY p.family ORDER BY coste DESC LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "LA FAMILIA QUE MÁS PESA",
                        f"{r[0]['familia']}: {eur(r[0]['coste'])} en riesgo, y el lote "
                        f"más próximo caduca en {r[0]['primeros_dias']} días.",
                        "Por valor, no por número de lotes. Doce lotes de algo barato "
                        "hacen mucho ruido y poco daño.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Qué caduca, semana a semana",
                    "esq3",
                    "almacen",
                    f"""SELECT TO_CHAR(DATE_TRUNC('week', l.best_before), 'YYYY-MM-DD')
                                 AS semana,
                               ROUND(SUM(s.quantity * p.unit_cost)) AS coste
                        {_CADUCA} AND l.best_before >= CURRENT_DATE
                          AND l.best_before < CURRENT_DATE + 90
                        GROUP BY 1 ORDER BY 1""",
                    variante="column",
                    x="semana",
                    y="coste",
                ),
                grafico(
                    "Riesgo por zona de almacén",
                    "dir3",
                    "almacen",
                    f"""SELECT s.zone AS zona,
                               ROUND(SUM(s.quantity * p.unit_cost)) AS coste
                        {_CADUCA} AND l.best_before < CURRENT_DATE + 60
                        GROUP BY s.zone ORDER BY coste DESC""",
                    variante="pie",
                    x="zona",
                    y="coste",
                ),
                tabela(
                    "Caducidad por familia",
                    "larga4",
                    "catalogo",
                    f"""SELECT p.family AS "Familia",
                               COUNT(DISTINCT p.id) AS "Referencias",
                               COUNT(*) AS "Lotes",
                               SUM(s.quantity) AS "Unidades",
                               ROUND(AVG(p.shelf_life_days)) AS "Vida útil (días)",
                               MIN(l.best_before - CURRENT_DATE) AS "El más próximo",
                               ROUND(SUM(s.quantity * p.unit_cost)) AS "Coste (€)"
                        {_CADUCA} AND l.best_before < CURRENT_DATE + 60
                        GROUP BY p.family ORDER BY 7 DESC""",
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
                    "Facturado en el periodo",
                    "kpi1",
                    "comercial",
                    f"SELECT COALESCE(ROUND(SUM({_VENDA})), 0) AS v {_MARGEM}",
                    legenda="18 meses de pedidos servidos",
                    formato="currency",
                ),
                kpi(
                    "Margen bruto",
                    "kpi2",
                    "catalogo",
                    f"SELECT ROUND(100.0 * SUM({_BRUTO}) / NULLIF(SUM({_VENDA}), 0), 1) AS v "
                    f"{_MARGEM}",
                    legenda="El que se celebra en enero",
                    formato="percent",
                ),
                kpi(
                    "Margen neto tras rappel",
                    "kpi3",
                    "comercial",
                    f"SELECT ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS v "
                    f"{_MARGEM}",
                    legenda="El que queda en diciembre",
                    formato="percent",
                ),
                kpi(
                    "Lo que cuesta el rappel",
                    "kpi4",
                    "comercial",
                    f"SELECT COALESCE(ROUND(SUM({_BRUTO}) - SUM({_NETO})), 0) AS v {_MARGEM}",
                    legenda="Acordado en contrato, invisible en la factura",
                    formato="currency",
                ),
                grafico(
                    "Margen neto por canal",
                    "esq1",
                    "comercial",
                    f"""SELECT c.channel AS canal,
                               ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS neto
                        {_MARGEM} GROUP BY c.channel ORDER BY neto""",
                    variante="bar",
                    x="canal",
                    y="neto",
                ),
                tabela(
                    "Bruto contra neto, por canal",
                    "dir1",
                    "comercial",
                    f"""SELECT c.channel AS "Canal",
                               COUNT(DISTINCT o.id) AS "Pedidos",
                               ROUND(SUM({_VENDA})) AS "Facturado (€)",
                               ROUND(100.0 * SUM({_BRUTO}) / NULLIF(SUM({_VENDA}), 0), 1) AS "Bruto (%)",
                               ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS "Neto (%)",
                               ROUND(SUM({_BRUTO}) - SUM({_NETO})) AS "Rappel (€)"
                        {_MARGEM} GROUP BY c.channel ORDER BY 5""",
                ),
                texto(
                    "Lo que el rappel se lleva",
                    "terco1a",
                    "comercial",
                    f"""SELECT ROUND(100.0 * SUM({_BRUTO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS bruto,
                               ROUND(100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS neto,
                               ROUND(SUM({_BRUTO}) - SUM({_NETO})) AS rappel
                        {_MARGEM}""",
                    corpo=lambda r: paragrafos(
                        "EL MARGEN QUE NO ES EL SUYO",
                        f"Bruto {pct(r[0]['bruto'])}. Después del rappel, "
                        f"{pct(r[0]['neto'])}. La diferencia son "
                        f"{eur(r[0]['rappel'])}.",
                        "El rappel se liquida al final del año y no aparece en ninguna "
                        "línea de factura. El margen que usted mira al vender no es el "
                        "que le queda.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "Por qué el bruto engaña",
                    "terco1b",
                    "comercial",
                    f"""WITH canal AS (
                            SELECT c.channel,
                                   100.0 * SUM({_BRUTO})
                                     / NULLIF(SUM({_VENDA}), 0) AS bruto,
                                   100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0) AS neto
                            {_MARGEM} GROUP BY c.channel
                        )
                        SELECT ROUND(MAX(bruto) - MIN(bruto), 1) AS rango_bruto,
                               ROUND(MAX(neto) - MIN(neto), 1) AS rango_neto,
                               COUNT(*) AS canales
                        FROM canal""",
                    corpo=lambda r: paragrafos(
                        "TODOS IGUALES, HASTA QUE NO",
                        f"Entre los {r[0]['canales']} canales, el margen bruto varía "
                        f"{pct(r[0]['rango_bruto'])}. El neto varía "
                        f"{pct(r[0]['rango_neto'])}.",
                        "Es la prueba de que el problema no está en el precio de tarifa: "
                        "está en lo que se acordó fuera de la factura.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Dónde mirar primero",
                    "terco1c",
                    "comercial",
                    f"""SELECT c.name AS cliente,
                               ROUND(SUM({_BRUTO}) - SUM({_NETO})) AS rappel,
                               ROUND(100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS neto
                        {_MARGEM} GROUP BY c.id, c.name
                        ORDER BY SUM({_BRUTO}) - SUM({_NETO}) DESC LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "EL CONTRATO QUE MÁS PESA",
                        f"{r[0]['cliente']}: {eur(r[0]['rappel'])} de rappel, y queda "
                        f"con {pct(r[0]['neto'])} de margen neto.",
                        "No se renegocia un rappel sin este número. Con él, la "
                        "conversación es otra.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Margen neto mes a mes",
                    "esq2",
                    "comercial",
                    f"""SELECT TO_CHAR(DATE_TRUNC('month', o.ordered_at), 'YYYY-MM') AS mes,
                               ROUND(100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS neto
                        {_MARGEM} GROUP BY 1 ORDER BY 1""",
                    variante="line",
                    x="mes",
                    y="neto",
                ),
                grafico(
                    "Margen neto por familia",
                    "dir2",
                    "catalogo",
                    f"""SELECT p.family AS familia,
                               ROUND(100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS neto
                        {_MARGEM} GROUP BY p.family ORDER BY neto DESC""",
                    variante="column",
                    x="familia",
                    y="neto",
                ),
                tabela(
                    "Rappel por cliente",
                    "larga3",
                    "comercial",
                    f"""SELECT c.name AS "Cliente",
                               c.channel AS "Canal",
                               ROUND(100.0 * c.rebate_pct, 2) AS "Rappel contratado (%)",
                               COUNT(DISTINCT o.id) AS "Pedidos",
                               ROUND(SUM({_VENDA})) AS "Facturado (€)",
                               ROUND(SUM({_BRUTO}) - SUM({_NETO})) AS "Rappel (€)",
                               ROUND(100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS "Neto (%)"
                        {_MARGEM} GROUP BY c.id, c.name, c.channel, c.rebate_pct
                        ORDER BY 6 DESC""",
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
                    "Capital en almacén",
                    "kpi1",
                    "almacen",
                    """SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0""",
                    legenda="A coste, no a tarifa",
                    formato="currency",
                ),
                kpi(
                    "De guarda — parado a propósito",
                    "kpi2",
                    "catalogo",
                    """SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0 AND p.is_vintage""",
                    legenda="Esto es estrategia, no descuido",
                    formato="currency",
                ),
                kpi(
                    "Parado sin ser de guarda",
                    "kpi3",
                    "almacen",
                    """SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0 AND NOT p.is_vintage""",
                    legenda="Aquí es donde hay una conversación",
                    formato="currency",
                ),
                kpi(
                    "Referencias sin una sola venta",
                    "kpi4",
                    "catalogo",
                    """SELECT COUNT(*) AS v FROM assortment.products p
                       WHERE NOT EXISTS (
                           SELECT 1 FROM trade.order_lines ol
                           JOIN warehouse.lots l ON l.id = ol.lot_id
                           WHERE l.product_id = p.id)""",
                    legenda="Se compraron, se quedaron, nadie volvió a mirar",
                ),
                grafico(
                    "Capital parado por familia",
                    "esq1",
                    "catalogo",
                    """SELECT p.family AS familia,
                              ROUND(SUM(s.quantity * p.unit_cost)) AS capital
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0
                       GROUP BY p.family ORDER BY capital DESC""",
                    variante="bar",
                    x="familia",
                    y="capital",
                ),
                tabela(
                    "Las referencias más paradas",
                    "dir1",
                    "catalogo",
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
                texto(
                    "Las dos líneas que son iguales",
                    "terco1a",
                    "almacen",
                    """SELECT ROUND(SUM(s.quantity * p.unit_cost)) AS total,
                              ROUND(SUM(s.quantity * p.unit_cost)
                                    FILTER (WHERE p.is_vintage)) AS guarda,
                              ROUND(SUM(s.quantity * p.unit_cost)
                                    FILTER (WHERE NOT p.is_vintage)) AS resto
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0""",
                    corpo=lambda r: paragrafos(
                        "PARADO A PROPÓSITO, O PARADO",
                        f"{eur(r[0]['total'])} en almacén: {eur(r[0]['guarda'])} de "
                        f"guarda y {eur(r[0]['resto'])} que no lo son.",
                        "El vino de guarda está ahí porque tiene que estar. El resto está "
                        "ahí porque no se vendió. En su hoja de stock son la misma línea, "
                        "y por eso el segundo nunca se discute.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "Lo que nadie volvió a mirar",
                    "terco1b",
                    "catalogo",
                    """WITH sin_venta AS (
                           SELECT p.id, p.name,
                                  COALESCE(SUM(s.quantity * p.unit_cost), 0) AS capital
                           FROM assortment.products p
                           LEFT JOIN warehouse.lots l ON l.product_id = p.id
                           LEFT JOIN warehouse.stock s ON s.lot_id = l.id
                           WHERE NOT EXISTS (
                               SELECT 1 FROM trade.order_lines ol
                               JOIN warehouse.lots l2 ON l2.id = ol.lot_id
                               WHERE l2.product_id = p.id)
                           GROUP BY p.id, p.name
                       )
                       SELECT COUNT(*) AS refs,
                              ROUND(SUM(capital)) AS capital,
                              (SELECT name FROM sin_venta ORDER BY capital DESC LIMIT 1)
                                AS peor
                       FROM sin_venta""",
                    corpo=lambda r: paragrafos(
                        "SE COMPRARON Y SE QUEDARON",
                        f"{r[0]['refs']} referencias no han tenido ni una sola venta, con "
                        f"{eur(r[0]['capital'])} inmovilizados.",
                        f"La que más pesa: {r[0]['peor']}. Nadie decidió quedarse con "
                        "ellas — simplemente nadie volvió a mirar.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Lo que rota bien",
                    "terco1c",
                    "catalogo",
                    """WITH rota AS (
                           SELECT p.family,
                                  SUM(ol.quantity) AS vendido,
                                  COALESCE((SELECT SUM(s.quantity)
                                            FROM warehouse.stock s
                                            JOIN warehouse.lots l2 ON l2.id = s.lot_id
                                            JOIN assortment.products p2
                                              ON p2.id = l2.product_id
                                            WHERE p2.family = p.family), 0) AS en_stock
                           FROM trade.order_lines ol
                           JOIN warehouse.lots l ON l.id = ol.lot_id
                           JOIN assortment.products p ON p.id = l.product_id
                           GROUP BY p.family
                       )
                       SELECT family AS familia,
                              ROUND(vendido::NUMERIC / NULLIF(en_stock, 0), 1) AS vueltas
                       FROM rota
                       WHERE en_stock > 0
                       ORDER BY vendido::NUMERIC / NULLIF(en_stock, 0) DESC
                       LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "LA QUE SÍ SE MUEVE",
                        f"{r[0]['familia']} rota {r[0]['vueltas']} veces lo que tiene en "
                        "almacén.",
                        "Es el contrapeso de esta página: el capital parado no es un "
                        "problema del almacén, es un problema de algunas referencias.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Capital por zona",
                    "esq2",
                    "almacen",
                    """SELECT s.zone AS zona,
                              ROUND(SUM(s.quantity * p.unit_cost)) AS capital
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0
                       GROUP BY s.zone ORDER BY capital DESC""",
                    variante="pie",
                    x="zona",
                    y="capital",
                ),
                grafico(
                    "Antigüedad del lote en almacén",
                    "dir2",
                    "almacen",
                    """SELECT TO_CHAR(DATE_TRUNC('month', l.received_on), 'YYYY-MM') AS mes,
                              ROUND(SUM(s.quantity * p.unit_cost)) AS capital
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0
                       GROUP BY 1 ORDER BY 1""",
                    variante="area",
                    x="mes",
                    y="capital",
                ),
                tabela(
                    "Capital y rotación por familia",
                    "larga3",
                    "catalogo",
                    """SELECT p.family AS "Familia",
                              COUNT(DISTINCT p.id) AS "Referencias",
                              SUM(s.quantity) AS "Unidades",
                              ROUND(SUM(s.quantity * p.unit_cost)) AS "Capital (€)",
                              COUNT(DISTINCT p.id) FILTER (WHERE p.is_vintage)
                                AS "De guarda",
                              ROUND(AVG(CURRENT_DATE - l.received_on))
                                AS "Días en almacén"
                       FROM warehouse.stock s
                       JOIN warehouse.lots l ON l.id = s.lot_id
                       JOIN assortment.products p ON p.id = l.product_id
                       WHERE s.quantity > 0
                       GROUP BY p.family ORDER BY 4 DESC""",
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
                    "La plaza que más factura",
                    "kpi1",
                    "comercial",
                    f"""SELECT c.city AS v {_MARGEM}
                        GROUP BY c.city ORDER BY SUM({_VENDA}) DESC LIMIT 1""",
                    legenda="Por importe servido",
                ),
                kpi(
                    "El canal que más deja",
                    "kpi2",
                    "comercial",
                    f"""SELECT c.channel AS v {_MARGEM}
                        GROUP BY c.channel
                        ORDER BY SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0) DESC LIMIT 1""",
                    legenda="Por margen neto, no por facturación",
                ),
                kpi(
                    "Pedidos servidos",
                    "kpi3",
                    "comercial",
                    "SELECT COUNT(*) AS v FROM trade.orders WHERE status = 'delivered'",
                    legenda="18 meses",
                ),
                kpi(
                    "Ticket medio",
                    "kpi4",
                    "comercial",
                    f"""SELECT ROUND(SUM({_VENDA}) / NULLIF(COUNT(DISTINCT o.id), 0)) AS v
                        {_MARGEM}""",
                    legenda="Importe medio por pedido servido",
                    formato="currency",
                ),
                grafico(
                    "Facturación por plaza",
                    "esq1",
                    "comercial",
                    f"""SELECT c.city AS plaza, ROUND(SUM({_VENDA})) AS facturado
                        {_MARGEM} GROUP BY c.city ORDER BY facturado DESC""",
                    variante="bar",
                    x="plaza",
                    y="facturado",
                ),
                tabela(
                    "Los clientes que más pesan",
                    "dir1",
                    "comercial",
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
                texto(
                    "Facturar mucho y dejar poco",
                    "terco1a",
                    "comercial",
                    f"""WITH cliente AS (
                            SELECT c.name,
                                   SUM({_VENDA}) AS factura,
                                   100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0) AS neto
                            {_MARGEM} GROUP BY c.id, c.name
                        )
                        SELECT (SELECT name FROM cliente ORDER BY factura DESC LIMIT 1)
                                 AS top_factura,
                               (SELECT ROUND(neto, 1) FROM cliente
                                  ORDER BY factura DESC LIMIT 1) AS top_neto,
                               ROUND(AVG(neto), 1) AS neto_medio,
                               COUNT(*) FILTER (WHERE neto < (SELECT AVG(neto) FROM cliente))
                                 AS bajo_media
                        FROM cliente""",
                    corpo=lambda r: paragrafos(
                        "EL QUE MÁS FACTURA NO ES EL MEJOR",
                        f"{r[0]['top_factura']} es el primero por importe y deja "
                        f"{pct(r[0]['top_neto'])}, contra una media de "
                        f"{pct(r[0]['neto_medio'])}.",
                        f"{r[0]['bajo_media']} clientes están por debajo de la media. El "
                        "ranking por facturación es el que todo el mundo mira y el que "
                        "menos dice.",
                    ),
                    cor=AMBAR,
                ),
                texto(
                    "La plaza no es el canal",
                    "terco1b",
                    "comercial",
                    f"""SELECT COUNT(DISTINCT c.city) AS plazas,
                               COUNT(DISTINCT c.channel) AS canales,
                               COUNT(DISTINCT c.id) AS clientes
                        {_MARGEM}""",
                    corpo=lambda r: paragrafos(
                        "DOS FORMAS DE CORTAR LO MISMO",
                        f"{r[0]['clientes']} clientes en {r[0]['plazas']} plazas y "
                        f"{r[0]['canales']} canales.",
                        "La plaza dice dónde está el comercial; el canal dice cómo se "
                        "vende. Mezclarlas en un solo informe es lo que hace que ninguna "
                        "de las dos decisiones se pueda tomar.",
                    ),
                    cor=AZUL,
                ),
                texto(
                    "Dónde crecer",
                    "terco1c",
                    "comercial",
                    f"""SELECT c.city AS plaza,
                               ROUND(100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS neto,
                               ROUND(SUM({_VENDA})) AS facturado
                        {_MARGEM} GROUP BY c.city
                        ORDER BY SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0) DESC
                        LIMIT 1""",
                    corpo=lambda r: paragrafos(
                        "LA PLAZA QUE MEJOR DEJA",
                        f"{r[0]['plaza']}: {pct(r[0]['neto'])} de margen neto sobre "
                        f"{eur(r[0]['facturado'])} facturados.",
                        "Si hay que meter un comercial más, es aquí — y esta es la única "
                        "página que lo dice sin pedirle que lo intuya.",
                    ),
                    cor=VERDE,
                ),
                grafico(
                    "Margen neto por plaza",
                    "esq2",
                    "comercial",
                    f"""SELECT c.city AS plaza,
                               ROUND(100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS neto
                        {_MARGEM} GROUP BY c.city ORDER BY neto DESC""",
                    variante="column",
                    x="plaza",
                    y="neto",
                ),
                grafico(
                    "Reparto de la facturación por canal",
                    "dir2",
                    "comercial",
                    f"""SELECT c.channel AS canal, ROUND(SUM({_VENDA})) AS facturado
                        {_MARGEM} GROUP BY c.channel ORDER BY facturado DESC""",
                    variante="pie",
                    x="canal",
                    y="facturado",
                ),
                tabela(
                    "Plazas: importe, ticket y margen",
                    "larga3",
                    "comercial",
                    f"""SELECT c.city AS "Plaza",
                               COUNT(DISTINCT c.id) AS "Clientes",
                               COUNT(DISTINCT o.id) AS "Pedidos",
                               ROUND(SUM({_VENDA})) AS "Facturado (€)",
                               ROUND(SUM({_VENDA})
                                     / NULLIF(COUNT(DISTINCT o.id), 0)) AS "Ticket (€)",
                               ROUND(100.0 * SUM({_NETO})
                                     / NULLIF(SUM({_VENDA}), 0), 1) AS "Neto (%)"
                        {_MARGEM} GROUP BY c.city ORDER BY 4 DESC""",
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


# ── as perguntas ─────────────────────────────────────────────────────
#
# Cinco fios já respondidos. A resposta é função do resultado da
# consulta, não texto escrito à mão — ver `pecas.Pergunta`.

# (o `formato` já vem importado no topo do ficheiro)
from scripts.demo_sectorial.pecas import Pergunta  # noqa: E402

P_CADUCA = """SELECT p.family AS familia,
       COUNT(*) AS lotes,
       SUM(s.quantity) AS unidades,
       ROUND(SUM(s.quantity * p.unit_cost)) AS coste,
       MIN(l.best_before - CURRENT_DATE) AS dias_min
FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0 AND NOT p.is_vintage
  AND l.best_before < CURRENT_DATE + 60
GROUP BY p.family ORDER BY coste DESC"""

P_PARADO = """SELECT p.family AS familia,
       CASE WHEN p.is_vintage THEN 'de guarda' ELSE 'rotación' END AS tipo,
       COUNT(DISTINCT p.id) AS referencias,
       ROUND(SUM(s.quantity * p.unit_cost)) AS capital
FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0
GROUP BY p.family, p.is_vintage ORDER BY capital DESC"""

P_SEM_VENDA = """SELECT p.sku AS sku, p.name AS nombre, p.family AS familia,
       ROUND(SUM(s.quantity * p.unit_cost)) AS capital
FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0
  AND NOT EXISTS (
      SELECT 1 FROM trade.order_lines ol
      JOIN warehouse.lots l2 ON l2.id = ol.lot_id
      WHERE l2.product_id = p.id
  )
GROUP BY p.id, p.sku, p.name, p.family ORDER BY capital DESC"""

P_RAPPEL = f"""SELECT c.channel AS canal,
       COUNT(DISTINCT o.id) AS pedidos,
       ROUND(SUM({_VENDA})) AS facturado,
       ROUND(100.0 * SUM({_BRUTO}) / NULLIF(SUM({_VENDA}), 0), 1) AS bruto_pct,
       ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS neto_pct,
       ROUND(SUM({_BRUTO}) - SUM({_NETO})) AS rappel
{_MARGEM} GROUP BY c.channel ORDER BY neto_pct"""

P_CLIENTES = f"""SELECT c.name AS cliente, c.channel AS canal, c.city AS plaza,
       COUNT(DISTINCT o.id) AS pedidos,
       ROUND(SUM({_VENDA})) AS facturado,
       ROUND(100.0 * c.rebate_pct, 2) AS rappel_pct,
       ROUND(100.0 * SUM({_NETO}) / NULLIF(SUM({_VENDA}), 0), 1) AS neto_pct
{_MARGEM}
GROUP BY c.id, c.name, c.channel, c.city, c.rebate_pct
ORDER BY facturado DESC LIMIT 12"""


def _r_caduca(linhas):
    if not linhas:
        return "No hay lotes con caducidad próxima."
    total = sum(float(r["coste"] or 0) for r in linhas)
    detalhe = "\n".join(
        f"- {r['familia']}: {eur(r['coste'])} en {r['lotes']} lotes, "
        f"{n(r['unidades'])} unidades, el más próximo a {r['dias_min']} días"
        for r in linhas
    )
    return (
        f"{detalhe}\n\n"
        f"En total **{eur(total)} de mercancía con menos de 60 días**.\n\n"
        "Están excluidos los vinos de guarda: en esos el tiempo no es un "
        "riesgo, es el producto. Mezclarlos aquí es lo que hace que la cifra "
        "deje de significar nada y nadie la mire."
    )


def _r_parado(linhas):
    if not linhas:
        return "No hay existencias en almacén."
    guarda = sum(float(r["capital"] or 0) for r in linhas if r["tipo"] == "de guarda")
    rotacao = sum(float(r["capital"] or 0) for r in linhas if r["tipo"] == "rotación")
    detalhe = "\n".join(
        f"- {r['familia']} ({r['tipo']}): {eur(r['capital'])} en " f"{r['referencias']} referencias"
        for r in linhas
    )
    return (
        f"{detalhe}\n\n"
        f"**{eur(rotacao)} parados sin ser de guarda**, frente a "
        f"{eur(guarda)} que lo están a propósito.\n\n"
        "La diferencia es toda: el vino de guarda está ahí porque tiene que "
        "estar, y el resto está ahí porque no se vendió. Sumados en una sola "
        "línea de balance son indistinguibles, y por eso el segundo nunca se "
        "discute."
    )


def _r_sem_venda(linhas):
    if not linhas:
        return "Todas las referencias en almacén han tenido alguna venta."
    total = sum(float(r["capital"] or 0) for r in linhas)
    detalhe = "\n".join(
        f"- {r['sku']} {r['nombre']} ({r['familia']}): {eur(r['capital'])}" for r in linhas
    )
    return (
        f"{detalhe}\n\n"
        f"**{len(linhas)} referencias sin una sola venta**, {eur(total)} de "
        "capital.\n\n"
        "No es que vendan poco: es que no han salido ni una vez. En un informe "
        "de rotación aparecen abajo del todo, junto a las que venden despacio, "
        "y ahí dejan de distinguirse — que es justo lo contrario de lo que "
        "hace falta para decidir si se descatalogan."
    )


def _r_rappel(linhas):
    if not linhas:
        return "No hay pedidos en el periodo."
    rappel = sum(float(r["rappel"] or 0) for r in linhas)
    detalhe = "\n".join(
        f"- {r['canal']}: bruto {pct(r['bruto_pct'])} → neto {pct(r['neto_pct'])}, "
        f"{eur(r['rappel'])} de rappel sobre {eur(r['facturado'])}"
        for r in linhas
    )
    pior = linhas[0]
    return (
        f"{detalhe}\n\n"
        f"El rappel cuesta **{eur(rappel)}** en el periodo, y el canal donde "
        f"más aprieta es **{pior['canal']}**: {pct(pior['bruto_pct'])} de "
        f"margen bruto se quedan en {pct(pior['neto_pct'])}.\n\n"
        "El rappel se liquida a final de año y no aparece en la línea del "
        "pedido. El margen que se mira al vender no es el que queda — y la "
        "diferencia no está repartida por igual entre los canales."
    )


def _r_clientes(linhas):
    if not linhas:
        return "No hay pedidos en el periodo."
    detalhe = "\n".join(
        f"- {r['cliente']} ({r['canal']}, {r['plaza']}): {eur(r['facturado'])}, "
        f"rappel {pct(r['rappel_pct'])}, neto {pct(r['neto_pct'])}"
        for r in linhas
    )
    por_neto = sorted(linhas, key=lambda r: float(r["neto_pct"] or 0))
    pior, melhor = por_neto[0], por_neto[-1]
    return (
        f"{detalhe}\n\n"
        f"Por facturación manda **{linhas[0]['cliente']}**; por margen neto, "
        f"**{melhor['cliente']}** ({pct(melhor['neto_pct'])}) está muy por "
        f"encima de **{pior['cliente']}** ({pct(pior['neto_pct'])}).\n\n"
        "Ordenar la cartera por facturación es lo que mantiene arriba a los "
        "clientes que más rappel se llevan. El orden que importa para decidir "
        "es el del neto."
    )


SECTOR.perguntas = [
    Pergunta(
        texto="¿Qué mercancía caduca en los próximos 60 días?",
        esquemas=["almacen", "catalogo"],
        sql=P_CADUCA,
        pagina="Caducidad por lote",
        resposta=_r_caduca,
    ),
    Pergunta(
        texto="¿Cuánto capital tengo parado en almacén, y cuánto es de guarda?",
        esquemas=["almacen", "catalogo"],
        sql=P_PARADO,
        pagina="Capital parado",
        resposta=_r_parado,
    ),
    Pergunta(
        texto="¿Qué referencias no han tenido ni una sola venta?",
        esquemas=["catalogo", "almacen", "comercial"],
        sql=P_SEM_VENDA,
        pagina="Capital parado",
        resposta=_r_sem_venda,
    ),
    Pergunta(
        texto="¿Cuánto me come el rappel, y en qué canal?",
        esquemas=["comercial", "almacen", "catalogo"],
        sql=P_RAPPEL,
        pagina="Margen real",
        resposta=_r_rappel,
    ),
    Pergunta(
        texto="¿Qué clientes facturan mucho y dejan poco?",
        esquemas=["comercial", "almacen", "catalogo"],
        sql=P_CLIENTES,
        pagina="Clientes y plaza",
        resposta=_r_clientes,
    ),
]
