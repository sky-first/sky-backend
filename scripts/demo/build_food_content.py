# -*- coding: utf-8 -*-
"""Conteúdo curado do sector Alimentação e Bebidas.

    python scripts/demo/build_food_content.py
    python scripts/demo/_es_food_pairs.py
    python scripts/demo/build_es_content.py
    python scripts/curate_demo_content.py --verify-sql --apply

Já existia um sector de Distribuição genérico e não chega para quem
distribui comida e vinho. Três coisas distinguem este negócio:

  • **a mercadoria morre.** A validade está no lote; o stock vê-se por
    referência. São duas vistas da mesma caixa e só uma tem a data;
  • **o preço não é o preço.** O rappel aplica-se sobre o acumulado, no
    fim, e não aparece em nenhuma linha de factura;
  • **o stock parado às vezes é estratégia.** O vinho de guarda e o
    esquecimento são a mesma linha numa folha de stock.

Os dados vêm de `scripts/demo/seed_food.sql` — sintéticos, de ninguém.
"""

from __future__ import annotations

import json
from pathlib import Path

ALVO = Path(__file__).resolve().parents[2] / "scripts" / "demo" / "curated_content.json"

# ── blocos ───────────────────────────────────────────────────────────

# O vinho de guarda sai da conta da caducidade: ele não caduca,
# envelhece. Metê-lo aqui inventava um problema que não existe.
_EM_ARMAZEM = """FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0 AND NOT p.is_vintage"""

_VENDAS = """FROM trade.order_lines ol
JOIN trade.orders o ON o.id = ol.order_id
JOIN trade.customers c ON c.id = o.customer_id
JOIN warehouse.lots l ON l.id = ol.lot_id
JOIN assortment.products p ON p.id = l.product_id"""

_BRUTO = "ol.quantity * (ol.unit_price * (1 - ol.discount) - p.unit_cost)"
_LIQUIDO = (
    "ol.quantity * (ol.unit_price * (1 - ol.discount) * (1 - c.rebate_pct) "
    "- p.unit_cost)"
)
_VENDA = "ol.quantity * ol.unit_price * (1 - ol.discount)"

SQL_CADUCIDADE = """SELECT l.lot_code AS lot,
       p.name AS product,
       p.family,
       l.best_before,
       (l.best_before - CURRENT_DATE) AS days_left,
       s.quantity AS units,
       ROUND(s.quantity * p.unit_cost) AS cost,
       s.zone
FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0 AND NOT p.is_vintage
  AND l.best_before < CURRENT_DATE + 60
ORDER BY l.best_before
LIMIT 40"""

SQL_RAPPEL = f"""SELECT c.channel,
       COUNT(DISTINCT o.id) AS orders,
       ROUND(SUM({_VENDA})) AS billed,
       ROUND(100.0 * SUM({_BRUTO}) / NULLIF(SUM({_VENDA}), 0), 1) AS gross_pct,
       ROUND(100.0 * SUM({_LIQUIDO}) / NULLIF(SUM({_VENDA}), 0), 1) AS net_pct,
       ROUND(SUM({_BRUTO}) - SUM({_LIQUIDO})) AS rebate_cost
{_VENDAS}
GROUP BY c.channel
ORDER BY net_pct"""

SQL_PARADO = """SELECT p.sku, p.name, p.family,
       CASE WHEN p.is_vintage THEN 'sí' ELSE 'no' END AS vintage,
       SUM(s.quantity) AS units,
       ROUND(SUM(s.quantity * p.unit_cost)) AS capital
FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0
GROUP BY p.id, p.sku, p.name, p.family, p.is_vintage
ORDER BY capital DESC
LIMIT 40"""

SQL_CLIENTES = f"""SELECT c.name, c.channel, c.city,
       COUNT(DISTINCT o.id) AS orders,
       ROUND(SUM({_VENDA})) AS billed,
       ROUND(100.0 * c.rebate_pct, 2) AS rebate_pct,
       ROUND(100.0 * SUM({_LIQUIDO}) / NULLIF(SUM({_VENDA}), 0), 1) AS net_pct
{_VENDAS}
GROUP BY c.id, c.name, c.channel, c.city, c.rebate_pct
ORDER BY billed DESC
LIMIT 30"""

SQL_FAMILIAS = f"""SELECT p.family,
       ROUND(SUM({_VENDA})) AS billed,
       ROUND(100.0 * SUM({_BRUTO}) / NULLIF(SUM({_VENDA}), 0), 1) AS gross_pct,
       ROUND(100.0 * SUM({_LIQUIDO}) / NULLIF(SUM({_VENDA}), 0), 1) AS net_pct
{_VENDAS}
GROUP BY p.family
ORDER BY net_pct"""

SQL_PRACAS = f"""SELECT c.city,
       COUNT(DISTINCT c.id) AS customers,
       COUNT(DISTINCT o.id) AS orders,
       ROUND(SUM({_VENDA})) AS billed,
       ROUND(100.0 * SUM({_LIQUIDO}) / NULLIF(SUM({_VENDA}), 0), 1) AS net_pct
{_VENDAS}
GROUP BY c.city
ORDER BY billed DESC"""

# ── séries ───────────────────────────────────────────────────────────

SQL_SERIE_CADUCA = """SELECT TO_CHAR(DATE_TRUNC('month', l.best_before), 'YYYY-MM') AS t,
       ROUND(SUM(s.quantity * p.unit_cost)) AS v
FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0 AND NOT p.is_vintage
  AND l.best_before BETWEEN CURRENT_DATE - 180 AND CURRENT_DATE + 180
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_MARGEM = f"""SELECT TO_CHAR(DATE_TRUNC('month', o.ordered_at), 'YYYY-MM') AS t,
       ROUND(100.0 * SUM({_LIQUIDO}) / NULLIF(SUM({_VENDA}), 0), 1) AS v
{_VENDAS}
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_CAPITAL = """SELECT p.family AS t,
       ROUND(SUM(s.quantity * p.unit_cost)) AS v
FROM warehouse.stock s
JOIN warehouse.lots l ON l.id = s.lot_id
JOIN assortment.products p ON p.id = l.product_id
WHERE s.quantity > 0
GROUP BY p.family ORDER BY v DESC"""

# ── valores escalares ────────────────────────────────────────────────

V = {
    "caducado": (
        f"SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) {_EM_ARMAZEM} "
        "AND l.best_before < CURRENT_DATE"
    ),
    "caduca_60": (
        f"SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) {_EM_ARMAZEM} "
        "AND l.best_before >= CURRENT_DATE AND l.best_before < CURRENT_DATE + 60"
    ),
    "lotes_em_risco": (
        f"SELECT COUNT(*) {_EM_ARMAZEM} AND l.best_before < CURRENT_DATE + 60"
    ),
    "familia_exposta": (
        f"SELECT p.family {_EM_ARMAZEM} AND l.best_before < CURRENT_DATE + 60 "
        "GROUP BY p.family ORDER BY SUM(s.quantity * p.unit_cost) DESC LIMIT 1"
    ),
    "facturado": f"SELECT COALESCE(ROUND(SUM({_VENDA})), 0) {_VENDAS}",
    "margem_bruta": (
        f"SELECT ROUND(100.0 * SUM({_BRUTO}) / NULLIF(SUM({_VENDA}), 0), 1) {_VENDAS}"
    ),
    "margem_liquida": (
        f"SELECT ROUND(100.0 * SUM({_LIQUIDO}) / NULLIF(SUM({_VENDA}), 0), 1) {_VENDAS}"
    ),
    "custo_do_rappel": (
        f"SELECT COALESCE(ROUND(SUM({_BRUTO}) - SUM({_LIQUIDO})), 0) {_VENDAS}"
    ),
    "canal_pior": (
        f"SELECT c.channel {_VENDAS} GROUP BY c.channel "
        f"ORDER BY SUM({_LIQUIDO}) / NULLIF(SUM({_VENDA}), 0) LIMIT 1"
    ),
    "capital_total": (
        "SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) "
        "FROM warehouse.stock s JOIN warehouse.lots l ON l.id = s.lot_id "
        "JOIN assortment.products p ON p.id = l.product_id WHERE s.quantity > 0"
    ),
    "capital_de_guarda": (
        "SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) "
        "FROM warehouse.stock s JOIN warehouse.lots l ON l.id = s.lot_id "
        "JOIN assortment.products p ON p.id = l.product_id "
        "WHERE s.quantity > 0 AND p.is_vintage"
    ),
    "capital_sem_ser_guarda": (
        "SELECT COALESCE(ROUND(SUM(s.quantity * p.unit_cost)), 0) "
        "FROM warehouse.stock s JOIN warehouse.lots l ON l.id = s.lot_id "
        "JOIN assortment.products p ON p.id = l.product_id "
        "WHERE s.quantity > 0 AND NOT p.is_vintage"
    ),
    "refs_sem_venda": (
        "SELECT COUNT(*) FROM assortment.products p WHERE NOT EXISTS ("
        "SELECT 1 FROM trade.order_lines ol JOIN warehouse.lots l ON l.id = ol.lot_id "
        "WHERE l.product_id = p.id)"
    ),
    "praca_maior": (
        f"SELECT c.city {_VENDAS} GROUP BY c.city ORDER BY SUM({_VENDA}) DESC LIMIT 1"
    ),
    "pedidos": "SELECT COUNT(*) FROM trade.orders WHERE status = 'delivered'",
    "clientes": "SELECT COUNT(*) FROM trade.customers",
    "referencias": "SELECT COUNT(*) FROM assortment.products",
}

_FONTES = [
    ("warehouse.lots", "O lote: quando entrou, quando caduca",
     "The lot: when it arrived, when it expires"),
    ("warehouse.stock", "Quanto resta de cada lote, e em que zona",
     "How much of each lot is left, and in which zone"),
    ("assortment.products", "Referência, família, custo e preço de tarifa",
     "Reference, family, cost and list price"),
    ("trade.customers", "Canal, praça, e o rappel acordado",
     "Channel, town, and the agreed rebate"),
    ("trade.order_lines", "O que saiu, de que lote, e por quanto",
     "What went out, from which lot, and for how much"),
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
        "vertical": "food",
        "locale": locale,
        "is_default": False,
        "name": L("Distribuidora Guadiana — alimentação selecta e vinhos",
                  "Guadiana Fine Foods — speciality food and wine"),
        "description": L(
            "Distribuidora à hostelaria com 72 referências, 360 lotes e 18 meses "
            "de encomendas.",
            "Distributor to the hospitality trade with 72 references, 360 lots and "
            "18 months of orders."),
        "connection_ref": L("Demo — Alimentar", "Demo — Food"),
        "insight": {
            "severity": "expiry_exposure",
            "severity_level": "warning",
            "agent_name": L("Armazém", "Warehouse"),
            "title": L("Há mercadoria a caducar que ainda se vendia — e outra que já não",
                       "There is stock expiring that could still be sold — and some that cannot"),
            "summary": L(
                "O stock vê-se por referência. A validade está no lote. São duas "
                "vistas da mesma caixa e só uma delas tem a data — por isso a "
                "pergunta «o que caduca este mês» não tem resposta em nenhum dos "
                "dois sítios sozinho.\n\n"
                "A distinção que interessa não é entre bom e mau: é entre o que "
                "ainda se consegue escoar e o que já se perdeu. O primeiro é uma "
                "campanha com duas semanas de aviso; o segundo é uma quebra que "
                "só se descobre a inventariar.\n\n"
                "O vinho de guarda fica de fora desta conta de propósito. Ele não "
                "caduca — envelhece — e metê-lo aqui inventava um problema que não "
                "existe.",
                "Stock is seen by reference. The date is on the lot. Two views of "
                "the same box and only one of them has the date — which is why "
                "\"what expires this month\" has no answer in either place "
                "alone.\n\n"
                "The distinction that matters is not good versus bad: it is between "
                "what can still be moved and what is already lost. The first is a "
                "campaign with a fortnight's notice; the second is shrinkage you "
                "only find at stocktake.\n\n"
                "Vintage wine is deliberately left out of this count. It does not "
                "expire — it ages — and including it would invent a problem that "
                "does not exist."),
            "stat_tiles": [
                tile(L("Já caducado em armazém", "Already expired in the warehouse"),
                     "caducado", "eur"),
                tile(L("Caduca nos próximos 60 dias", "Expires in the next 60 days"),
                     "caduca_60", "eur"),
                tile(L("A família mais exposta", "The most exposed family"),
                     "familia_exposta"),
            ],
            "sources": [F[0], F[1], F[2]],
            "executed_sql": SQL_CADUCIDADE,
            "series_sql": SQL_SERIE_CADUCA,
        },
        "extra_insights": [
            {
                "severity": "rebate_erosion",
                "severity_level": "warning",
                "agent_name": L("Margem", "Margin"),
                "title": L("A margem bruta é igual em todos os canais. A líquida não é.",
                           "Gross margin is the same across every channel. Net margin is not."),
                "summary": L(
                    "O rappel acordado aplica-se sobre o acumulado, no fim do ano, e "
                    "não aparece em nenhuma linha de factura. Por isso o relatório de "
                    "vendas mostra a mesma margem em todos os canais — e está certo, "
                    "até ao dia em que não está.\n\n"
                    "O número só existe cruzando o que foi vendido com a percentagem "
                    "que está no contrato de cada cliente. Um dos dois vive na "
                    "facturação, o outro vive numa pasta.\n\n"
                    "A diferença entre as duas colunas é dinheiro que já foi "
                    "prometido e ainda não foi contado.",
                    "The agreed rebate applies to the running total, at year end, and "
                    "appears on no invoice line. So the sales report shows the same "
                    "margin on every channel — and it is right, until the day it "
                    "isn't.\n\n"
                    "The number only exists by crossing what was sold with the "
                    "percentage in each client's contract. One of the two lives in "
                    "billing, the other lives in a folder.\n\n"
                    "The gap between the two columns is money already promised and "
                    "not yet counted."),
                "stat_tiles": [
                    tile(L("Margem bruta", "Gross margin"), "margem_bruta", "pct"),
                    tile(L("Margem líquida após rappel", "Net margin after rebate"),
                         "margem_liquida", "pct"),
                    tile(L("O que o rappel custa", "What the rebate costs"),
                         "custo_do_rappel", "eur"),
                ],
                "sources": [F[4], F[3], F[2]],
                "executed_sql": SQL_RAPPEL,
                "series_sql": SQL_SERIE_MARGEM,
            },
            {
                "severity": "idle_capital",
                "severity_level": "info",
                # «Stock» é a mesma palavra em inglês e em castelhano, e o
                # teste diferencial do espanhol apanhou-o — com razão. Um
                # nome de agente que não muda entre idiomas não prova que
                # a tradução chegou cá. «Existências» e «Inventario» são
                # as palavras próprias de cada língua, e são melhores.
                "agent_name": L("Existências", "Stock"),
                "title": L("Capital parado por estratégia e capital parado por esquecimento",
                           "Capital parked on purpose, and capital parked by forgetting"),
                "summary": L(
                    "Numa folha de stock os dois são a mesma linha: mercadoria que "
                    "não se mexeu. Mas um vinho de guarda que não se mexe está a "
                    "fazer o seu trabalho, e uma referência que entrou para um "
                    "cliente que entretanto fechou está a ocupar dinheiro e "
                    "prateleira.\n\n"
                    "O que separa os dois não é a quantidade nem o tempo — é se "
                    "alguma vez se vendeu. Essa coluna não existe no stock; existe "
                    "na facturação.\n\n"
                    "As referências que nunca tiveram uma única venda são o caso "
                    "extremo, e existem em qualquer catálogo.",
                    "On a stock sheet the two are the same line: goods that have not "
                    "moved. But a vintage wine that does not move is doing its job, "
                    "while a reference brought in for a client who has since closed "
                    "is taking up both money and shelf.\n\n"
                    "What separates them is neither quantity nor time — it is whether "
                    "it ever sold at all. That column does not exist in stock; it "
                    "exists in billing.\n\n"
                    "References with not a single sale are the extreme case, and they "
                    "exist in every catalogue."),
                "stat_tiles": [
                    tile(L("Parado sem ser de guarda", "Parked and not vintage"),
                         "capital_sem_ser_guarda", "eur"),
                    tile(L("De guarda — a propósito", "Vintage — on purpose"),
                         "capital_de_guarda", "eur"),
                    tile(L("Referências sem uma única venda",
                           "References with not a single sale"), "refs_sem_venda"),
                ],
                "sources": [F[1], F[2], F[4]],
                "executed_sql": SQL_PARADO,
                "series_sql": SQL_SERIE_CAPITAL,
            },
        ],
        "qas": [
            {
                "position": 0,
                "is_suggested": True,
                "question": L("O que é que está a caducar, e quanto vale?",
                              "What is expiring, and what is it worth?"),
                "answer_markdown": L(
                    "**Separado entre o que ainda se vende e o que já se perdeu.** "
                    "São dois problemas diferentes e só um deles tem solução.\n\n"
                    "O que caduca nas próximas semanas é uma campanha: há tempo de "
                    "escoar com desconto, de propor ao cliente certo, de mudar de "
                    "praça. O que já passou do prazo é uma quebra — resta decidir "
                    "como se contabiliza.\n\n"
                    "A lista vem por lote e não por referência, porque é o lote que "
                    "tem a data. Com o stock por referência esta pergunta não tem "
                    "resposta: a mesma referência tem lotes de meses diferentes.",
                    "**Split between what can still be sold and what is already "
                    "lost.** They are two different problems and only one has a "
                    "solution.\n\n"
                    "What expires in the coming weeks is a campaign: there is time to "
                    "move it at a discount, offer it to the right client, shift it to "
                    "another town. What is already past date is shrinkage — all that "
                    "is left is deciding how to book it.\n\n"
                    "The list comes by lot and not by reference, because it is the "
                    "lot that carries the date. With stock by reference this question "
                    "has no answer: the same reference has lots from different "
                    "months."),
                "citations": [{"table": "warehouse.lots"}, {"table": "warehouse.stock"}],
                "executed_sql": SQL_CADUCIDADE,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Já caducado", "Already expired"), "caducado", "eur"),
                    tile(L("Caduca em 60 dias", "Expires within 60 days"),
                         "caduca_60", "eur"),
                    tile(L("Lotes em risco", "Lots at risk"), "lotes_em_risco"),
                ],
            },
            {
                "position": 1,
                "is_suggested": True,
                "question": L("Quanto é que o rappel me está mesmo a custar?",
                              "What is the rebate actually costing me?"),
                "answer_markdown": L(
                    "**Mais no canal que negoceia melhor, como seria de esperar — e "
                    "a diferença não aparece em lado nenhum até Dezembro.**\n\n"
                    "A margem bruta é praticamente igual em todos os canais: a tabela "
                    "de preços é a mesma. A líquida separa-os, e a separação é o "
                    "contrato, não a venda.\n\n"
                    "O quadro põe as duas lado a lado por canal. A última coluna é o "
                    "euro que já foi prometido e ainda não foi lançado — e é essa "
                    "que decide se vale a pena crescer naquele canal.",
                    "**Most in the channel that negotiates best, as you would expect "
                    "— and the difference shows up nowhere until December.**\n\n"
                    "Gross margin is practically the same on every channel: the rate "
                    "card is the same. Net margin separates them, and the separation "
                    "is the contract, not the sale.\n\n"
                    "The table puts the two side by side per channel. The last column "
                    "is the euro already promised and not yet booked — and that is "
                    "the one that decides whether growing in that channel is worth "
                    "it."),
                "citations": [{"table": "trade.customers"}, {"table": "trade.order_lines"}],
                "executed_sql": SQL_RAPPEL,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Margem bruta", "Gross margin"), "margem_bruta", "pct"),
                    tile(L("Margem líquida", "Net margin"), "margem_liquida", "pct"),
                    tile(L("O que o rappel custa", "What the rebate costs"),
                         "custo_do_rappel", "eur"),
                ],
            },
            {
                "position": 2,
                "is_suggested": True,
                "question": L("Que capital tenho parado, e qual dele é de propósito?",
                              "How much capital is parked, and how much on purpose?"),
                "answer_markdown": L(
                    "**A separação é a resposta.** O total sozinho não serve para "
                    "decidir nada, porque mistura duas coisas opostas.\n\n"
                    "O vinho de guarda está parado porque deve estar — é o modelo de "
                    "negócio. O resto está parado porque alguém comprou e ninguém "
                    "voltou a olhar.\n\n"
                    "O caso extremo são as referências sem uma única venda: entraram "
                    "para um cliente concreto, esse cliente mudou, e elas ficaram. "
                    "Não aparecem em nenhum relatório de rotação porque rotação zero "
                    "não gera linhas.",
                    "**The split is the answer.** The total on its own decides "
                    "nothing, because it mixes two opposite things.\n\n"
                    "Vintage wine is parked because it should be — that is the "
                    "business model. The rest is parked because somebody bought it "
                    "and nobody looked again.\n\n"
                    "The extreme case is references with not a single sale: they came "
                    "in for one specific client, that client moved on, and they "
                    "stayed. They appear in no turnover report, because zero turnover "
                    "produces no rows."),
                "citations": [{"table": "warehouse.stock"}, {"table": "assortment.products"}],
                "executed_sql": SQL_PARADO,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Parado sem ser de guarda", "Parked and not vintage"),
                         "capital_sem_ser_guarda", "eur"),
                    tile(L("De guarda", "Vintage"), "capital_de_guarda", "eur"),
                    tile(L("Sem uma única venda", "Not a single sale"), "refs_sem_venda"),
                ],
            },
            {
                "position": 3,
                "is_suggested": False,
                "question": L("Que famílias deixam menos depois do rappel?",
                              "Which families leave least after the rebate?"),
                "answer_markdown": L(
                    "**Por margem líquida, que é a ordem que decide o catálogo.** A "
                    "bruta ordena quase sempre de outra maneira.\n\n"
                    "Uma família com boa margem de tarifa que se vende sobretudo ao "
                    "canal com mais rappel acaba abaixo de outra com tarifa pior e "
                    "clientes que não negoceiam. Isso não se vê na ficha do produto.",
                    "**By net margin, which is the order that decides the catalogue.** "
                    "Gross margin almost always sorts differently.\n\n"
                    "A family with a good rate-card margin that sells mostly to the "
                    "channel with the biggest rebate ends up below one with a worse "
                    "rate card and clients who do not negotiate. None of that is on "
                    "the product sheet."),
                "citations": [{"table": "assortment.products"}, {"table": "trade.order_lines"}],
                "executed_sql": SQL_FAMILIAS,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Facturado no período", "Billed in the period"),
                         "facturado", "eur"),
                    tile(L("Margem líquida", "Net margin"), "margem_liquida", "pct"),
                    tile(L("Referências no catálogo", "References in the catalogue"),
                         "referencias"),
                ],
            },
            {
                "position": 4,
                "is_suggested": False,
                "question": L("Que clientes pesam mais, e quais deixam mais?",
                              "Which clients weigh most, and which leave most?"),
                "answer_markdown": L(
                    "**São listas diferentes, e é essa a utilidade de as ver "
                    "juntas.**\n\n"
                    "O cliente que mais factura costuma ser o que mais negoceia — foi "
                    "assim que chegou a esse volume. A coluna da margem líquida ao "
                    "lado da facturação diz quanto desse volume chega ao fim.\n\n"
                    "Não é um argumento para o perder. É um argumento para saber "
                    "quanto custa mantê-lo antes da próxima negociação.",
                    "**They are different lists, and that is the point of seeing them "
                    "together.**\n\n"
                    "The client who bills most is usually the one who negotiates most "
                    "— that is how they got to that volume. The net-margin column "
                    "beside the billing says how much of that volume reaches the "
                    "end.\n\n"
                    "It is not an argument for losing them. It is an argument for "
                    "knowing what keeping them costs, before the next negotiation."),
                "citations": [{"table": "trade.customers"}, {"table": "trade.orders"}],
                "executed_sql": SQL_CLIENTES,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Clientes activos", "Active clients"), "clientes"),
                    tile(L("Encomendas servidas", "Orders delivered"), "pedidos"),
                    tile(L("O canal que menos deixa", "The channel that leaves least"),
                         "canal_pior"),
                ],
            },
            {
                "position": 5,
                "is_suggested": False,
                "question": L("Que praças compram mais, e quais compensam?",
                              "Which towns buy most, and which pay off?"),
                "answer_markdown": L(
                    "**Facturação e margem líquida por praça, lado a lado.** A praça "
                    "que mais factura não é sempre a que mais deixa.\n\n"
                    "Numa zona onde se entrega duas vezes por semana a clientes "
                    "pequenos, o volume é baixo e o rappel também. Noutra, meia dúzia "
                    "de contas grandes fazem o número e levam a margem com elas.\n\n"
                    "É a conta que decide onde vale a pena pôr mais um comercial.",
                    "**Billing and net margin per town, side by side.** The town that "
                    "bills most is not always the one that leaves most.\n\n"
                    "In an area served twice a week to small accounts, volume is low "
                    "and so is the rebate. In another, half a dozen large accounts "
                    "make the number and take the margin with them.\n\n"
                    "It is the sum that decides where another salesperson is worth "
                    "it."),
                "citations": [{"table": "trade.customers"}, {"table": "trade.order_lines"}],
                "executed_sql": SQL_PRACAS,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("A praça que mais factura", "The town that bills most"),
                         "praca_maior"),
                    tile(L("Facturado no período", "Billed in the period"),
                         "facturado", "eur"),
                    tile(L("Clientes activos", "Active clients"), "clientes"),
                ],
            },
        ],
    }


def main() -> None:
    doc = json.loads(ALVO.read_text(encoding="utf-8"))
    outros = [
        d for d in doc["datasets"]
        if not (d["vertical"] == "food" and d["locale"] in ("pt", "en"))
    ]
    doc["datasets"] = outros + [dataset("pt"), dataset("en")]
    ALVO.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"food pt+en escritos em {ALVO.name}")


if __name__ == "__main__":
    main()
