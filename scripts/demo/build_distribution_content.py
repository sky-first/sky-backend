# -*- coding: utf-8 -*-
"""Gera o conteúdo curado do sector Distribuição / Retalho.

Existe como script e não como JSON escrito à mão por uma razão: o mesmo
conteúdo vive em dois idiomas e o **SQL é partilhado**. Manter as duas
versões sincronizadas à mão é o caminho mais curto para uma delas ficar
para trás — e foi assim que a demo acabou uma vez com a interface num
idioma e o conteúdo no outro.

Correr com:
    python scripts/demo/build_distribution_content.py

Escreve por cima dos blocos `distribution` em `curated_content.json` e
não toca em mais nada. Depois:
    python scripts/curate_demo_content.py --verify-sql --apply
"""

from __future__ import annotations

import io
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ALVO = RAIZ / "scripts" / "demo" / "curated_content.json"

# ── SQL, partilhado pelos dois idiomas ───────────────────────────────

FAMILIA_PIOR = (
    "SELECT p.family FROM sales.order_lines l "
    "JOIN catalog.products p ON p.id = l.product_id "
    "GROUP BY p.family ORDER BY AVG(l.discount) DESC LIMIT 1"
)
FORN_PIOR = (
    "SELECT sup.name FROM supply.receipts r "
    "JOIN supply.suppliers sup ON sup.id = r.supplier_id "
    "WHERE r.received_at IS NOT NULL GROUP BY sup.name "
    "ORDER BY AVG(r.received_at - r.promised_at) DESC LIMIT 1"
)

SQL_MARGEM = """SELECT p.family,
       ROUND(SUM(l.quantity * l.unit_price * (1 - l.discount))) AS revenue,
       ROUND(100.0 * AVG(l.discount), 1) AS avg_discount_pct,
       ROUND(100.0 * SUM(l.quantity * (l.unit_price * (1 - l.discount) - p.unit_cost))
             / NULLIF(SUM(l.quantity * l.unit_price * (1 - l.discount)), 0), 1) AS margin_pct
FROM sales.order_lines l
JOIN catalog.products p ON p.id = l.product_id
GROUP BY p.family
ORDER BY margin_pct"""

SQL_STOCK = """SELECT p.sku, p.name, w.name AS warehouse, s.quantity,
       ROUND(s.quantity * p.unit_cost) AS euros,
       CURRENT_DATE - s.last_movement AS days_still
FROM inventory.stock s
JOIN catalog.products p ON p.id = s.product_id
JOIN inventory.warehouses w ON w.id = s.warehouse_id
WHERE s.last_movement < CURRENT_DATE - 180
ORDER BY euros DESC"""

SQL_ATRASO = """SELECT sup.name, sup.country, sup.lead_time_days,
       COUNT(*) AS receipts,
       ROUND(AVG(r.received_at - r.promised_at), 1) AS avg_days_late
FROM supply.receipts r
JOIN supply.suppliers sup ON sup.id = r.supplier_id
WHERE r.received_at IS NOT NULL
GROUP BY sup.name, sup.country, sup.lead_time_days
ORDER BY avg_days_late DESC"""

SQL_CANAL = """SELECT c.channel, COUNT(DISTINCT o.id) AS orders,
       ROUND(SUM(l.quantity * l.unit_price * (1 - l.discount))) AS revenue,
       ROUND(100.0 * SUM(l.quantity * (l.unit_price * (1 - l.discount) - p.unit_cost))
             / NULLIF(SUM(l.quantity * l.unit_price * (1 - l.discount)), 0), 1) AS margin_pct
FROM sales.orders o
JOIN sales.customers c ON c.id = o.customer_id
JOIN sales.order_lines l ON l.order_id = o.id
JOIN catalog.products p ON p.id = l.product_id
GROUP BY c.channel
ORDER BY margin_pct DESC"""

SQL_CLIENTES = """SELECT c.name, c.channel,
       ROUND(SUM(l.quantity * l.unit_price * (1 - l.discount))) AS revenue
FROM sales.customers c
JOIN sales.orders o ON o.customer_id = c.id
JOIN sales.order_lines l ON l.order_id = o.id
GROUP BY c.name, c.channel
ORDER BY revenue DESC
LIMIT 10"""

SQL_SEM_VENDAS = """SELECT p.sku, p.name, SUM(s.quantity) AS in_stock
FROM catalog.products p
JOIN inventory.stock s ON s.product_id = p.id
LEFT JOIN sales.order_lines l ON l.product_id = p.id
WHERE l.id IS NULL
GROUP BY p.sku, p.name
ORDER BY in_stock DESC"""

SQL_SERIE_RECEITA = """SELECT DATE_TRUNC('month', o.ordered_at)::date AS t,
       ROUND(SUM(l.quantity * l.unit_price * (1 - l.discount))) AS v
FROM sales.orders o
JOIN sales.order_lines l ON l.order_id = o.id
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_MARGEM = """SELECT DATE_TRUNC('month', o.ordered_at)::date AS t,
       ROUND(100.0 * SUM(l.quantity * (l.unit_price * (1 - l.discount) - p.unit_cost))
             / NULLIF(SUM(l.quantity * l.unit_price * (1 - l.discount)), 0), 1) AS v
FROM sales.order_lines l
JOIN sales.orders o ON o.id = l.order_id
JOIN catalog.products p ON p.id = l.product_id
WHERE p.family = (%s)
GROUP BY 1 ORDER BY 1""" % FAMILIA_PIOR

SQL_SERIE_STOCK = """SELECT b.faixa AS t, COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) AS v
FROM (VALUES (1,'180-220'),(2,'221-260'),(3,'261-300'),(4,'301+')) AS b(ord, faixa)
LEFT JOIN inventory.stock s ON s.last_movement < CURRENT_DATE - 180
 AND width_bucket(CURRENT_DATE - s.last_movement, ARRAY[221,261,301]) + 1 = b.ord
LEFT JOIN catalog.products p ON p.id = s.product_id
GROUP BY b.ord, b.faixa ORDER BY b.ord"""

SQL_SERIE_ATRASO = """SELECT DATE_TRUNC('month', r.promised_at)::date AS t,
       ROUND(AVG(r.received_at - r.promised_at), 1) AS v
FROM supply.receipts r
JOIN supply.suppliers sup ON sup.id = r.supplier_id
WHERE r.received_at IS NOT NULL AND sup.name = (%s)
GROUP BY 1 ORDER BY 1""" % FORN_PIOR

# valores escalares
V = {
    "familia_pior": FAMILIA_PIOR,
    "desconto_pior": (
        "SELECT ROUND(100.0 * AVG(l.discount), 1) FROM sales.order_lines l "
        "JOIN catalog.products p ON p.id = l.product_id WHERE p.family = (%s)" % FAMILIA_PIOR
    ),
    "margem_pior": (
        "SELECT ROUND(100.0 * SUM(l.quantity * (l.unit_price * (1 - l.discount) - p.unit_cost))"
        " / NULLIF(SUM(l.quantity * l.unit_price * (1 - l.discount)), 0), 1) "
        "FROM sales.order_lines l JOIN catalog.products p ON p.id = l.product_id "
        "WHERE p.family = (%s)" % FAMILIA_PIOR
    ),
    "stock_refs": "SELECT COUNT(*) FROM inventory.stock WHERE last_movement < CURRENT_DATE - 180",
    "stock_euros": (
        "SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) FROM inventory.stock s "
        "JOIN catalog.products p ON p.id = s.product_id "
        "WHERE s.last_movement < CURRENT_DATE - 180"
    ),
    "stock_dias": (
        "SELECT COALESCE(MAX(CURRENT_DATE - last_movement), 0) FROM inventory.stock "
        "WHERE last_movement < CURRENT_DATE - 180"
    ),
    "forn_pior": FORN_PIOR,
    "atraso_dias": (
        "SELECT ROUND(MAX(m), 1) FROM (SELECT AVG(r.received_at - r.promised_at) m "
        "FROM supply.receipts r WHERE r.received_at IS NOT NULL GROUP BY r.supplier_id) x"
    ),
    "atraso_n": (
        "SELECT COUNT(*) FROM supply.receipts r JOIN supply.suppliers sup ON sup.id = r.supplier_id "
        "WHERE r.received_at IS NOT NULL AND sup.name = (%s)" % FORN_PIOR
    ),
    "canal_melhor": (
        "SELECT c.channel FROM sales.orders o JOIN sales.customers c ON c.id = o.customer_id "
        "JOIN sales.order_lines l ON l.order_id = o.id JOIN catalog.products p ON p.id = l.product_id "
        "GROUP BY c.channel ORDER BY SUM(l.quantity * (l.unit_price * (1 - l.discount) - p.unit_cost))"
        " / NULLIF(SUM(l.quantity * l.unit_price * (1 - l.discount)), 0) DESC LIMIT 1"
    ),
    "receita_total": (
        "SELECT COALESCE(ROUND(SUM(l.quantity * l.unit_price * (1 - l.discount))), 0) "
        "FROM sales.order_lines l"
    ),
    "margem_global": (
        "SELECT ROUND(100.0 * SUM(l.quantity * (l.unit_price * (1 - l.discount) - p.unit_cost))"
        " / NULLIF(SUM(l.quantity * l.unit_price * (1 - l.discount)), 0), 1) "
        "FROM sales.order_lines l JOIN catalog.products p ON p.id = l.product_id"
    ),
    "cliente_top": (
        "SELECT c.name FROM sales.customers c JOIN sales.orders o ON o.customer_id = c.id "
        "JOIN sales.order_lines l ON l.order_id = o.id GROUP BY c.name "
        "ORDER BY SUM(l.quantity * l.unit_price * (1 - l.discount)) DESC LIMIT 1"
    ),
    "encomendas": "SELECT COUNT(*) FROM sales.orders WHERE status = 'delivered'",
    "sem_vendas_n": (
        "SELECT COUNT(*) FROM (SELECT p.id FROM catalog.products p "
        "JOIN inventory.stock s ON s.product_id = p.id "
        "LEFT JOIN sales.order_lines l ON l.product_id = p.id "
        "WHERE l.id IS NULL GROUP BY p.id) x"
    ),
}

FONTES = [
    {"table": "sales.order_lines", "description": "Linhas de encomenda, com desconto"},
    {"table": "catalog.products", "description": "Custo e preço de tabela"},
    {"table": "inventory.stock", "description": "Quantidade e última movimentação"},
    {"table": "supply.receipts", "description": "Prometido contra recebido"},
]


def tile(rotulo, chave, formato=None):
    t = {"label": rotulo, "value_sql": V[chave]}
    if formato:
        t["format"] = formato
    return t


def dataset(locale):
    pt = locale == "pt"
    L = (lambda a, b: a if pt else b)

    return {
        "vertical": "distribution",
        "locale": locale,
        "is_default": False,
        "name": L("Distribuidora Atlântico — Retalho alimentar",
                  "Atlantico Wholesale — Food retail"),
        "description": L(
            "Distribuidor com 100 clientes de revenda e horeca, 60 referências e quatro armazéns.",
            "Wholesaler with 100 resale and horeca customers, 60 SKUs and four warehouses."),
        "connection_ref": L("Demo — Distribuição", "Demo — Distribution"),
        "insight": {
            "severity": "margin_leak",
            "severity_level": "warning",
            "agent_name": L("Margem", "Margin Watch"),
            "title": L(
                "Uma família inteira vendida com desconto seis vezes maior que o resto",
                "One whole family sold at six times the discount of everything else"),
            "summary": L(
                "O desconto não está a ser negociado encomenda a encomenda — está aplicado de "
                "forma sistemática a uma família inteira. O custo dessa família não é diferente "
                "do resto do catálogo; o que é diferente é o preço à saída. É por isso que a "
                "margem aparece onde ninguém a foi procurar: no ficheiro de vendas, não no de "
                "compras.",
                "The discount isn't being negotiated order by order — it's applied systematically "
                "across a whole family. That family's cost is no different from the rest of the "
                "catalogue; what's different is the price at the till. Which is why the margin "
                "shows up where nobody went looking: in the sales file, not the buying file."),
            "stat_tiles": [
                tile(L("Família com maior desconto", "Family with the largest discount"), "familia_pior"),
                tile(L("Desconto médio", "Average discount"), "desconto_pior", "pct"),
                tile(L("Margem que sobra", "Margin left"), "margem_pior", "pct"),
            ],
            "sources": FONTES,
            "executed_sql": SQL_MARGEM,
            "series_sql": SQL_SERIE_MARGEM,
        },
        "extra_insights": [
            {
                "severity": "cash_in_stock",
                "severity_level": "warning",
                "agent_name": L("Inventário", "Inventory"),
                "title": L("Dinheiro parado em prateleira há mais de meio ano",
                           "Cash sitting on a shelf for more than six months"),
                "summary": L(
                    "Stock parado não aparece em lado nenhum como custo — está pago, está "
                    "contabilizado como activo, e continua lá. O agente olha para a data do "
                    "último movimento e não para a quantidade, porque a quantidade parece "
                    "saudável até ao dia em que se percebe que ninguém lhe toca.",
                    "Idle stock shows up nowhere as a cost — it's paid for, it's booked as an "
                    "asset, and there it stays. The agent watches the last movement date, not the "
                    "quantity, because the quantity looks healthy right up until you realise "
                    "nobody has touched it."),
                "stat_tiles": [
                    tile(L("Referências paradas", "SKUs not moving"), "stock_refs"),
                    tile(L("Valor imobilizado", "Cash tied up"), "stock_euros", "eur"),
                    tile(L("A mais antiga, em dias", "Oldest, in days"), "stock_dias"),
                ],
                "sources": [FONTES[2], FONTES[1]],
                "executed_sql": SQL_STOCK,
                "series_sql": SQL_SERIE_STOCK,
            },
            {
                "severity": "supplier_delay",
                "severity_level": "info",
                "agent_name": L("Fornecedores", "Supply"),
                "title": L("Um fornecedor entrega sempre tarde. Os outros não.",
                           "One supplier is always late. The others aren't."),
                "summary": L(
                    "Um atraso é ruído. O mesmo atraso todos os meses é um prazo mal acordado — e "
                    "é uma conversa que se tem com um número à frente, não de memória. Comparar "
                    "o prometido com o recebido é trivial; o que ninguém faz é fazê-lo todos os "
                    "meses, para todos os fornecedores.",
                    "One late delivery is noise. The same delay every month is a lead time that "
                    "was agreed wrong — and that's a conversation you have with a number in front "
                    "of you, not from memory. Comparing promised against received is trivial; "
                    "what nobody does is do it every month, for every supplier."),
                "stat_tiles": [
                    tile(L("Fornecedor", "Supplier"), "forn_pior"),
                    tile(L("Atraso médio, em dias", "Average delay, in days"), "atraso_dias"),
                    tile(L("Recepções afectadas", "Deliveries affected"), "atraso_n"),
                ],
                "sources": [FONTES[3]],
                "executed_sql": SQL_ATRASO,
                "series_sql": SQL_SERIE_ATRASO,
            },
        ],
        "qas": _qas(L, pt),
    }


def _qas(L, pt):
    return [
        {
            "position": 0,
            "is_suggested": True,
            "question": L("Que família de produtos está a perder margem, e porquê?",
                          "Which product family is losing margin, and why?"),
            "answer_markdown": L(
                "**É o desconto, não é o custo.** A família com pior margem é também a que leva o "
                "maior desconto médio — várias vezes acima do resto do catálogo, e aplicado de "
                "forma transversal e não caso a caso.\n\n"
                "Isto interessa porque muda quem resolve o problema. Se fosse custo, era uma "
                "conversa com o fornecedor; sendo desconto, é uma política de preço que alguém "
                "definiu e ninguém reviu.\n\n"
                "O número sai do cruzamento de duas tabelas que ninguém cruza: o preço praticado "
                "está nas linhas de encomenda, o custo está no catálogo.",
                "**It's the discount, not the cost.** The family with the worst margin is also the "
                "one carrying the largest average discount — several times the rest of the "
                "catalogue, and applied across the board rather than case by case.\n\n"
                "That matters because it changes who fixes it. If it were cost, it'd be a "
                "conversation with the supplier; being discount, it's a pricing policy somebody "
                "set and nobody revisited.\n\n"
                "The number comes from joining two tables nobody joins: the price actually "
                "charged is in the order lines, the cost is in the catalogue."),
            "citations": [{"table": "sales.order_lines"}, {"table": "catalog.products"}],
            "executed_sql": SQL_MARGEM,
            "chart_spec": None,
            "stat_tiles": [
                tile(L("Família", "Family"), "familia_pior"),
                tile(L("Desconto médio", "Average discount"), "desconto_pior", "pct"),
                tile(L("Margem que sobra", "Margin left"), "margem_pior", "pct"),
            ],
        },
        {
            "position": 1,
            "is_suggested": True,
            "question": L("Quanto dinheiro está parado em stock que não mexe?",
                          "How much cash is sitting in stock that doesn't move?"),
            "answer_markdown": L(
                "**Está tudo em poucas referências.** O valor imobilizado concentra-se num punhado "
                "de artigos que não têm movimento há mais de meio ano — e a mais antiga já passou "
                "os dez meses.\n\n"
                "Stock parado é o custo mais fácil de ignorar porque não aparece em lado nenhum "
                "como custo: está pago, está no activo, e continua lá. Só a data do último "
                "movimento o denuncia.\n\n"
                "Com uma lista destas, a decisão é operacional: promoção, devolução ao fornecedor, "
                "ou abate. Sem ela, a decisão nunca chega a ser tomada.",
                "**It's concentrated in a handful of SKUs.** The tied-up cash sits in a few items "
                "with no movement for over six months — and the oldest is past ten.\n\n"
                "Idle stock is the easiest cost to ignore because it shows up nowhere as a cost: "
                "it's paid for, it's on the balance sheet, and there it stays. Only the last "
                "movement date gives it away.\n\n"
                "With a list like this the decision is operational: promotion, return to supplier, "
                "or write-off. Without it, the decision simply never gets made."),
            "citations": [{"table": "inventory.stock"}, {"table": "catalog.products"}],
            "executed_sql": SQL_STOCK,
            "chart_spec": None,
            "stat_tiles": [
                tile(L("Referências paradas", "SKUs not moving"), "stock_refs"),
                tile(L("Valor imobilizado", "Cash tied up"), "stock_euros", "eur"),
                tile(L("A mais antiga, em dias", "Oldest, in days"), "stock_dias"),
            ],
        },
        {
            "position": 2,
            "is_suggested": True,
            "question": L("Que fornecedor entrega fora do prazo, e quanto?",
                          "Which supplier delivers late, and by how much?"),
            "answer_markdown": L(
                "**Um fornecedor destaca-se, e não por pouco.** A média de atraso dele está numa "
                "ordem de grandeza diferente da de todos os outros, que entregam praticamente "
                "dentro do prometido.\n\n"
                "É por isso que isto é accionável: não é o mercado, não é a época, é um "
                "fornecedor. O prazo que ele acordou não é o prazo que ele cumpre — e isso "
                "renegoceia-se com o histórico à frente.\n\n"
                "A comparação é entre o que ele prometeu e o que entregou, recepção a recepção.",
                "**One supplier stands out, and not by a little.** Its average delay is in a "
                "different order of magnitude from everyone else's — the rest deliver essentially "
                "on the promised date.\n\n"
                "That's what makes it actionable: it isn't the market, it isn't the season, it's "
                "one supplier. The lead time it agreed to isn't the lead time it keeps — and that "
                "gets renegotiated with the history in front of you.\n\n"
                "The comparison is promised against received, delivery by delivery."),
            "citations": [{"table": "supply.receipts"}, {"table": "supply.suppliers"}],
            "executed_sql": SQL_ATRASO,
            "chart_spec": None,
            "stat_tiles": [
                tile(L("Fornecedor", "Supplier"), "forn_pior"),
                tile(L("Atraso médio, em dias", "Average delay, in days"), "atraso_dias"),
                tile(L("Recepções afectadas", "Deliveries affected"), "atraso_n"),
            ],
        },
        {
            "position": 3,
            "is_suggested": False,
            "question": L("Que canal de venda dá mais margem — revenda, horeca, retalho ou online?",
                          "Which sales channel gives the most margin — resale, horeca, retail or online?"),
            "answer_markdown": L(
                "**O canal que factura mais não é o que deixa mais.** A ordem muda conforme se "
                "olha para a receita ou para a margem, e é essa diferença que decide onde vale a "
                "pena pôr comercial.\n\n"
                "Receita sem margem ao lado é uma métrica de vaidade: cresce, sente-se bem, e não "
                "diz se o negócio melhorou.",
                "**The channel that bills most isn't the one that keeps most.** The order changes "
                "depending on whether you look at revenue or margin, and that difference is what "
                "decides where the sales effort goes.\n\n"
                "Revenue without margin beside it is a vanity metric: it grows, it feels good, and "
                "it doesn't tell you whether the business got better."),
            "citations": [{"table": "sales.customers"}, {"table": "sales.order_lines"}],
            "executed_sql": SQL_CANAL,
            "chart_spec": None,
            "stat_tiles": [
                tile(L("Melhor canal por margem", "Best channel by margin"), "canal_melhor"),
                tile(L("Margem global", "Overall margin"), "margem_global", "pct"),
                tile(L("Receita total", "Total revenue"), "receita_total", "eur"),
            ],
        },
        {
            "position": 4,
            "is_suggested": False,
            "question": L("Quem são os maiores clientes, e em que canal?",
                          "Who are the largest customers, and in which channel?"),
            "answer_markdown": L(
                "**Os dez maiores, por receita entregue.** A lista sai das encomendas entregues, "
                "não das lançadas — canceladas não contam para ninguém.\n\n"
                "O canal ao lado do nome é o que torna isto útil: dois clientes com a mesma "
                "factura em canais diferentes não são o mesmo cliente para efeitos de margem.",
                "**The top ten, by delivered revenue.** The list comes from delivered orders, not "
                "placed ones — cancellations count for nobody.\n\n"
                "The channel beside the name is what makes it useful: two customers with the same "
                "invoice in different channels are not the same customer as far as margin goes."),
            "citations": [{"table": "sales.customers"}, {"table": "sales.orders"}],
            "executed_sql": SQL_CLIENTES,
            "chart_spec": None,
            "stat_tiles": [
                tile(L("Maior cliente", "Largest customer"), "cliente_top"),
                tile(L("Encomendas entregues", "Delivered orders"), "encomendas"),
                tile(L("Receita total", "Total revenue"), "receita_total", "eur"),
            ],
        },
        {
            "position": 5,
            "is_suggested": False,
            "question": L("Como evoluiu a facturação nos últimos meses?",
                          "How has revenue trended over the last months?"),
            "answer_markdown": L(
                "**Mês a mês, sobre encomendas entregues.** A série mostra a tendência e o ruído "
                "ao mesmo tempo — e é o ruído que costuma explicar as reuniões em que alguém "
                "pergunta porque é que o mês foi mau.\n\n"
                "Uma média mensal sozinha esconde exactamente a informação que interessa.",
                "**Month by month, on delivered orders.** The series shows the trend and the noise "
                "at the same time — and it's usually the noise that explains the meetings where "
                "somebody asks why the month was bad.\n\n"
                "A monthly average on its own hides precisely the information that matters."),
            "citations": [{"table": "sales.orders"}, {"table": "sales.order_lines"}],
            "executed_sql": SQL_SERIE_RECEITA,
            "chart_spec": None,
            "stat_tiles": [
                tile(L("Receita total", "Total revenue"), "receita_total", "eur"),
                tile(L("Encomendas entregues", "Delivered orders"), "encomendas"),
                tile(L("Margem global", "Overall margin"), "margem_global", "pct"),
            ],
        },
        {
            "position": 6,
            "is_suggested": False,
            "question": L("Que produtos têm stock mas nunca se venderam?",
                          "Which products have stock but never sold?"),
            "answer_markdown": L(
                "**Compraram-se e nunca saíram.** São referências com quantidade em armazém e "
                "zero linhas de venda em todo o histórico — o caso extremo do stock parado.\n\n"
                "Vale a pena olhar para elas antes da próxima encomenda ao fornecedor, que é "
                "exactamente quando ninguém olha.",
                "**Bought and never shipped.** These are SKUs with quantity in the warehouse and "
                "zero sales lines across the whole history — the extreme case of idle stock.\n\n"
                "Worth looking at before the next purchase order, which is exactly when nobody "
                "looks."),
            "citations": [{"table": "catalog.products"}, {"table": "inventory.stock"}],
            "executed_sql": SQL_SEM_VENDAS,
            "chart_spec": None,
            "stat_tiles": [
                tile(L("Referências sem uma venda", "SKUs with no sale"), "sem_vendas_n"),
                tile(L("Valor imobilizado", "Cash tied up"), "stock_euros", "eur"),
            ],
        },
    ]


def main() -> int:
    doc = json.loads(ALVO.read_text(encoding="utf-8"))
    # Substitui em vez de acrescentar: correr duas vezes não pode
    # duplicar o sector.
    doc["datasets"] = [d for d in doc["datasets"] if d.get("vertical") != "distribution"]
    doc["datasets"].append(dataset("pt"))
    doc["datasets"].append(dataset("en"))
    ALVO.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("distribution escrito nos dois idiomas; datasets no ficheiro:", len(doc["datasets"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
