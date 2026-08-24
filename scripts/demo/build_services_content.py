# -*- coding: utf-8 -*-
"""Conteúdo curado do sector Serviços / Consultoria.

Mesma razão do script da distribuição: o SQL é partilhado pelos dois
idiomas e só o texto muda. Ver `build_distribution_content.py`.

    python scripts/demo/build_services_content.py
    python scripts/curate_demo_content.py --verify-sql --apply
"""

from __future__ import annotations

import json
from pathlib import Path

ALVO = Path(__file__).resolve().parents[2] / "scripts" / "demo" / "curated_content.json"

# ── SQL ──────────────────────────────────────────────────────────────

SQL_UTILIZACAO = """SELECT c.name, c.grade,
       ROUND(SUM(t.hours)) AS hours,
       ROUND(SUM(CASE WHEN t.billable THEN t.hours ELSE 0 END)) AS billable_hours,
       ROUND(100.0 * SUM(CASE WHEN t.billable THEN t.hours ELSE 0 END)
             / NULLIF(SUM(t.hours), 0), 1) AS billable_pct
FROM people.consultants c
JOIN delivery.time_entries t ON t.consultant_id = c.id
GROUP BY c.name, c.grade
ORDER BY billable_pct"""

SQL_ESTOURO = """SELECT p.name, cl.name AS client, p.sold_hours,
       ROUND(SUM(t.hours)) AS burned_hours,
       ROUND(100.0 * SUM(t.hours) / NULLIF(p.sold_hours, 0)) AS pct_of_sold,
       ROUND((SUM(t.hours) - p.sold_hours) * p.rate_per_hour) AS overrun_value
FROM delivery.projects p
JOIN billing.clients cl ON cl.id = p.client_id
JOIN delivery.time_entries t ON t.project_id = p.id
WHERE p.contract_type = 'fixed_price'
GROUP BY p.id, p.name, cl.name, p.sold_hours, p.rate_per_hour
HAVING SUM(t.hours) > p.sold_hours
ORDER BY overrun_value DESC"""

SQL_POR_FATURAR = """SELECT p.name, cl.name AS client,
       ROUND(SUM(t.hours)) AS hours,
       ROUND(SUM(t.hours * p.rate_per_hour)) AS value,
       MIN(t.worked_on) AS oldest_entry
FROM delivery.time_entries t
JOIN delivery.projects p ON p.id = t.project_id
JOIN billing.clients cl ON cl.id = p.client_id
WHERE t.billable AND NOT t.invoiced
GROUP BY p.id, p.name, cl.name
ORDER BY value DESC"""

SQL_CLIENTES = """SELECT cl.name, cl.industry,
       COUNT(DISTINCT p.id) AS projects,
       ROUND(SUM(i.amount)) AS invoiced
FROM billing.clients cl
JOIN delivery.projects p ON p.client_id = cl.id
JOIN billing.invoices i ON i.project_id = p.id
GROUP BY cl.name, cl.industry
ORDER BY invoiced DESC"""

SQL_SERIE_UTIL = """SELECT DATE_TRUNC('month', t.worked_on)::date AS t,
       ROUND(100.0 * SUM(CASE WHEN t.billable THEN t.hours ELSE 0 END)
             / NULLIF(SUM(t.hours), 0), 1) AS v
FROM delivery.time_entries t
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_FATURA = """SELECT DATE_TRUNC('month', i.issued_at)::date AS t,
       ROUND(SUM(i.amount)) AS v
FROM billing.invoices i
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_ESTOURO = """SELECT p.name AS t, ROUND(SUM(t.hours) - p.sold_hours) AS v
FROM delivery.projects p
JOIN delivery.time_entries t ON t.project_id = p.id
WHERE p.contract_type = 'fixed_price'
GROUP BY p.id, p.name, p.sold_hours
HAVING SUM(t.hours) > p.sold_hours
ORDER BY v"""

SQL_CONTRATO = """SELECT p.contract_type,
       COUNT(DISTINCT p.id) AS projects,
       ROUND(SUM(t.hours)) AS hours,
       ROUND(SUM(i.amount)) AS invoiced
FROM delivery.projects p
LEFT JOIN delivery.time_entries t ON t.project_id = p.id
LEFT JOIN billing.invoices i ON i.project_id = p.id
GROUP BY p.contract_type"""

SQL_VENCIDAS = """SELECT cl.name AS client, p.name AS project, i.issued_at, i.amount
FROM billing.invoices i
JOIN delivery.projects p ON p.id = i.project_id
JOIN billing.clients cl ON cl.id = p.client_id
WHERE i.status = 'overdue'
ORDER BY i.issued_at"""

V = {
    "util_global": (
        "SELECT ROUND(100.0 * SUM(CASE WHEN billable THEN hours ELSE 0 END)"
        " / NULLIF(SUM(hours), 0), 1) FROM delivery.time_entries"
    ),
    "horas_totais": "SELECT ROUND(SUM(hours)) FROM delivery.time_entries",
    "horas_nao_faturaveis": (
        "SELECT ROUND(SUM(hours)) FROM delivery.time_entries WHERE NOT billable"
    ),
    "estouro_n": (
        "SELECT COUNT(*) FROM (SELECT p.id FROM delivery.projects p "
        "JOIN delivery.time_entries t ON t.project_id = p.id "
        "WHERE p.contract_type = 'fixed_price' GROUP BY p.id, p.sold_hours "
        "HAVING SUM(t.hours) > p.sold_hours) x"
    ),
    "estouro_pior": (
        "SELECT p.name FROM delivery.projects p JOIN delivery.time_entries t ON t.project_id = p.id "
        "WHERE p.contract_type = 'fixed_price' GROUP BY p.id, p.name, p.sold_hours, p.rate_per_hour "
        "HAVING SUM(t.hours) > p.sold_hours "
        "ORDER BY (SUM(t.hours) - p.sold_hours) * p.rate_per_hour DESC LIMIT 1"
    ),
    "estouro_valor": (
        "SELECT COALESCE(ROUND(SUM(x.v)), 0) FROM (SELECT (SUM(t.hours) - p.sold_hours) * p.rate_per_hour AS v "
        "FROM delivery.projects p JOIN delivery.time_entries t ON t.project_id = p.id "
        "WHERE p.contract_type = 'fixed_price' GROUP BY p.id, p.sold_hours, p.rate_per_hour "
        "HAVING SUM(t.hours) > p.sold_hours) x"
    ),
    "wip_horas": (
        "SELECT COALESCE(ROUND(SUM(hours)), 0) FROM delivery.time_entries "
        "WHERE billable AND NOT invoiced"
    ),
    "wip_euros": (
        "SELECT COALESCE(ROUND(SUM(t.hours * p.rate_per_hour)), 0) FROM delivery.time_entries t "
        "JOIN delivery.projects p ON p.id = t.project_id WHERE t.billable AND NOT t.invoiced"
    ),
    "wip_dias": (
        "SELECT COALESCE(CURRENT_DATE - MIN(worked_on), 0) FROM delivery.time_entries "
        "WHERE billable AND NOT invoiced"
    ),
    "faturado": "SELECT COALESCE(ROUND(SUM(amount)), 0) FROM billing.invoices",
    "cliente_top": (
        "SELECT cl.name FROM billing.clients cl JOIN delivery.projects p ON p.client_id = cl.id "
        "JOIN billing.invoices i ON i.project_id = p.id GROUP BY cl.name "
        "ORDER BY SUM(i.amount) DESC LIMIT 1"
    ),
    "projectos_activos": "SELECT COUNT(*) FROM delivery.projects WHERE status = 'active'",
    "vencidas_n": "SELECT COUNT(*) FROM billing.invoices WHERE status = 'overdue'",
    "vencidas_eur": (
        "SELECT COALESCE(ROUND(SUM(amount)), 0) FROM billing.invoices WHERE status = 'overdue'"
    ),
}

# As fontes, nos dois idiomas — ver a nota igual no construtor da
# distribuição: estavam em português também em inglês.
_FONTES = [
    ("delivery.time_entries", "Horas, faturáveis e faturadas", "Hours, billable and billed"),
    ("delivery.projects", "Contrato, horas vendidas, tarifa", "Contract, hours sold, rate"),
    ("people.consultants", "Escalão e custo hora", "Grade and hourly cost"),
    ("billing.invoices", "O que foi mesmo faturado", "What was actually invoiced"),
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
    FONTES = fontes(pt)

    return {
        "vertical": "services",
        "locale": locale,
        "is_default": False,
        "name": L("Consultora Meridiano — 14 consultores",
                  "Meridian Consulting — 14 consultants"),
        "description": L(
            "Consultora com 24 projectos activos, contratos de preço fixo e time-and-materials.",
            "Consultancy with 24 live projects, fixed-price and time-and-materials contracts."),
        "connection_ref": L("Demo — Serviços", "Demo — Services"),
        "insight": {
            "severity": "capacity_leak",
            "severity_level": "warning",
            "agent_name": L("Capacidade", "Utilisation"),
            "title": L("Um quarto das horas pagas não chega a ser faturável",
                       "A quarter of the hours you pay for never becomes billable"),
            "summary": L(
                "A capacidade não se perde de uma vez — perde-se meia hora de cada vez, em "
                "trabalho interno, pré-venda e formação, que ninguém regista como problema porque "
                "cada peça é razoável. Só a soma é que não é.\n\n"
                "O número só existe cruzando o registo de tempos com o contrato: as horas estão "
                "num sistema, o que era suposto ser faturável está noutro.",
                "Capacity doesn't leak all at once — it leaks half an hour at a time, in internal "
                "work, pre-sales and training, none of which anyone logs as a problem because "
                "each piece is reasonable. It's only the sum that isn't.\n\n"
                "The number only exists by joining the time log to the contract: the hours are in "
                "one system, what was meant to be billable is in another."),
            "stat_tiles": [
                tile(L("Horas faturáveis", "Billable hours"), "util_global", "pct"),
                tile(L("Horas registadas", "Hours logged"), "horas_totais"),
                tile(L("Horas não faturáveis", "Non-billable hours"), "horas_nao_faturaveis"),
            ],
            "sources": FONTES,
            "executed_sql": SQL_UTILIZACAO,
            "series_sql": SQL_SERIE_UTIL,
        },
        "extra_insights": [
            {
                "severity": "fixed_price_overrun",
                "severity_level": "warning",
                "agent_name": L("Projectos", "Delivery"),
                "title": L("Projectos de preço fixo já passaram as horas vendidas",
                           "Fixed-price projects have burned past the hours sold"),
                "summary": L(
                    "Num contrato de time-and-materials mais horas é mais fatura. Num de preço "
                    "fixo, mais horas é menos margem — e a diferença entre os dois casos não está "
                    "em nenhum relatório de horas, está no tipo de contrato.\n\n"
                    "O agente compara o consumido com o vendido, projecto a projecto, e só chama "
                    "quando o segundo já foi ultrapassado.",
                    "On a time-and-materials contract, more hours means more invoice. On a "
                    "fixed-price one, more hours means less margin — and the difference between "
                    "the two isn't in any timesheet report, it's in the contract type.\n\n"
                    "The agent compares burned against sold, project by project, and only calls "
                    "when the second has already been passed."),
                "stat_tiles": [
                    tile(L("Projectos em estouro", "Projects over"), "estouro_n"),
                    tile(L("Valor das horas a mais", "Value of the extra hours"), "estouro_valor", "eur"),
                    tile(L("O pior deles", "The worst of them"), "estouro_pior"),
                ],
                "sources": [FONTES[1], FONTES[0]],
                "executed_sql": SQL_ESTOURO,
                "series_sql": SQL_SERIE_ESTOURO,
            },
            {
                "severity": "unbilled_work",
                "severity_level": "info",
                "agent_name": L("Faturação", "Billing"),
                "title": L("Trabalho feito, faturável, e ainda não faturado",
                           "Work done, billable, and still not invoiced"),
                "summary": L(
                    "É o dinheiro mais fácil de cobrar e o mais fácil de esquecer: já foi "
                    "trabalhado, já foi marcado como faturável, e não chegou a entrar numa "
                    "fatura. Não é uma discussão com o cliente — é uma tarefa que ninguém fez.\n\n"
                    "Quanto mais antiga a hora, mais difícil é justificá-la. É por isso que o "
                    "agente mostra a data da mais velha.",
                    "This is the easiest money to collect and the easiest to forget: it's been "
                    "worked, it's been marked billable, and it never made it onto an invoice. "
                    "It isn't an argument with the client — it's a task nobody did.\n\n"
                    "The older the hour, the harder it is to justify. Which is why the agent "
                    "shows the date of the oldest one."),
                "stat_tiles": [
                    tile(L("Horas por faturar", "Hours unbilled"), "wip_horas"),
                    tile(L("Valor por faturar", "Value unbilled"), "wip_euros", "eur"),
                    tile(L("A mais antiga, em dias", "Oldest, in days"), "wip_dias"),
                ],
                "sources": [FONTES[0], FONTES[1]],
                "executed_sql": SQL_POR_FATURAR,
                "series_sql": None,
            },
        ],
        "qas": [
            {
                "position": 0,
                "is_suggested": True,
                "question": L("Quanto da capacidade da equipa é mesmo faturável?",
                              "How much of the team's capacity is actually billable?"),
                "answer_markdown": L(
                    "**Cerca de três quartos.** O resto vai para trabalho interno, pré-venda e "
                    "formação — nada disso é desperdício, mas nada disso entra numa fatura.\n\n"
                    "O que torna este número accionável é vê-lo por pessoa. A média esconde o "
                    "caso: há sempre quem esteja muito abaixo dela, e a razão nunca é a mesma "
                    "duas vezes.\n\n"
                    "Sai do cruzamento do registo de tempos com o escalão de cada consultor.",
                    "**About three quarters.** The rest goes to internal work, pre-sales and "
                    "training — none of it waste, none of it on an invoice.\n\n"
                    "What makes the number actionable is seeing it per person. The average hides "
                    "the case: there's always someone well below it, and the reason is never the "
                    "same twice.\n\n"
                    "It comes from joining the time log to each consultant's grade."),
                "citations": [{"table": "delivery.time_entries"}, {"table": "people.consultants"}],
                "executed_sql": SQL_UTILIZACAO,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Horas faturáveis", "Billable hours"), "util_global", "pct"),
                    tile(L("Horas registadas", "Hours logged"), "horas_totais"),
                    tile(L("Não faturáveis", "Non-billable"), "horas_nao_faturaveis"),
                ],
            },
            {
                "position": 1,
                "is_suggested": True,
                "question": L("Que projectos de preço fixo já gastaram mais horas do que venderam?",
                              "Which fixed-price projects have burned more hours than they sold?"),
                "answer_markdown": L(
                    "**São poucos, e custam muito.** Cada hora acima do vendido num contrato de "
                    "preço fixo sai directamente da margem — não há fatura do outro lado.\n\n"
                    "A lista está ordenada pelo valor dessas horas e não pela percentagem: um "
                    "estouro de 30% num projecto grande custa mais do que 90% num pequeno, e é o "
                    "primeiro que vale a pena travar.\n\n"
                    "Compara o registo de horas com as horas contratadas, projecto a projecto.",
                    "**There are few of them, and they cost a lot.** Every hour past the sold "
                    "number on a fixed-price contract comes straight out of margin — there's no "
                    "invoice on the other side.\n\n"
                    "The list is ordered by the value of those hours, not by percentage: a 30% "
                    "overrun on a large project costs more than 90% on a small one, and it's the "
                    "first one worth stopping.\n\n"
                    "It compares logged hours against contracted hours, project by project."),
                "citations": [{"table": "delivery.projects"}, {"table": "delivery.time_entries"}],
                "executed_sql": SQL_ESTOURO,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Projectos em estouro", "Projects over"), "estouro_n"),
                    tile(L("Valor das horas a mais", "Value of the extra hours"), "estouro_valor", "eur"),
                    tile(L("O pior deles", "The worst of them"), "estouro_pior"),
                ],
            },
            {
                "position": 2,
                "is_suggested": True,
                "question": L("Quanto trabalho está feito e ainda por faturar?",
                              "How much work is done and still unbilled?"),
                "answer_markdown": L(
                    "**Horas faturáveis que nunca entraram numa fatura.** O trabalho está feito e "
                    "aceite; falta o passo administrativo.\n\n"
                    "É a diferença entre resultado e tesouraria: o projecto parece rentável no "
                    "relatório e o dinheiro não entrou. E quanto mais velha for a hora, mais "
                    "difícil é justificá-la ao cliente.\n\n"
                    "Sai das horas marcadas como faturáveis e não faturadas, com a tarifa do "
                    "contrato aplicada.",
                    "**Billable hours that never made it onto an invoice.** The work is done and "
                    "accepted; what's missing is the admin step.\n\n"
                    "It's the difference between profit and cash: the project looks profitable in "
                    "the report and the money hasn't arrived. And the older the hour, the harder "
                    "it is to justify to the client.\n\n"
                    "It comes from hours marked billable and not invoiced, with the contract rate "
                    "applied."),
                "citations": [{"table": "delivery.time_entries"}, {"table": "billing.invoices"}],
                "executed_sql": SQL_POR_FATURAR,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Horas por faturar", "Hours unbilled"), "wip_horas"),
                    tile(L("Valor por faturar", "Value unbilled"), "wip_euros", "eur"),
                    tile(L("A mais antiga, em dias", "Oldest, in days"), "wip_dias"),
                ],
            },
            {
                "position": 3,
                "is_suggested": False,
                "question": L("Que clientes representam mais faturação?",
                              "Which clients account for the most billing?"),
                "answer_markdown": L(
                    "**Por valor faturado, com o número de projectos ao lado.** As duas colunas "
                    "juntas dizem coisas diferentes: muitos projectos pequenos e um projecto "
                    "grande dão a mesma fatura e não dão o mesmo risco.\n\n"
                    "A concentração num cliente é um dos poucos números que vale a pena olhar "
                    "todos os meses.",
                    "**By invoiced value, with the project count beside it.** The two columns "
                    "together say different things: many small projects and one large one produce "
                    "the same invoice and not the same risk.\n\n"
                    "Concentration in one client is one of the few numbers worth looking at every "
                    "month."),
                "citations": [{"table": "billing.clients"}, {"table": "billing.invoices"}],
                "executed_sql": SQL_CLIENTES,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Maior cliente", "Largest client"), "cliente_top"),
                    tile(L("Faturado no período", "Invoiced in the period"), "faturado", "eur"),
                    tile(L("Projectos activos", "Live projects"), "projectos_activos"),
                ],
            },
            {
                "position": 4,
                "is_suggested": False,
                "question": L("Preço fixo ou time-and-materials — qual rende mais?",
                              "Fixed price or time-and-materials — which pays better?"),
                "answer_markdown": L(
                    "**Depende de quanto se erra na estimativa.** O quadro põe lado a lado as "
                    "horas consumidas e o faturado por tipo de contrato.\n\n"
                    "O preço fixo só ganha enquanto a estimativa aguentar — e a estimativa é a "
                    "única variável que a empresa controla sozinha.",
                    "**It depends on how wrong the estimate is.** The table puts hours burned and "
                    "amount invoiced side by side, by contract type.\n\n"
                    "Fixed price only wins while the estimate holds — and the estimate is the one "
                    "variable the firm controls on its own."),
                "citations": [{"table": "delivery.projects"}, {"table": "billing.invoices"}],
                "executed_sql": SQL_CONTRATO,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Faturado no período", "Invoiced in the period"), "faturado", "eur"),
                    tile(L("Horas registadas", "Hours logged"), "horas_totais"),
                    tile(L("Projectos em estouro", "Projects over"), "estouro_n"),
                ],
            },
            {
                "position": 5,
                "is_suggested": False,
                "question": L("Que faturas estão vencidas?", "Which invoices are overdue?"),
                "answer_markdown": L(
                    "**Emitidas, aceites, e por receber.** A lista está por data de emissão e não "
                    "por valor: uma fatura antiga pequena é pior sinal do que uma recente grande.\n\n"
                    "Numa consultora, isto costuma competir com o trabalho por faturar — e são "
                    "problemas diferentes, com donos diferentes.",
                    "**Issued, accepted, and unpaid.** The list is by issue date, not amount: an "
                    "old small invoice is a worse sign than a recent large one.\n\n"
                    "In a consultancy this usually competes with unbilled work — and they're "
                    "different problems, with different owners."),
                "citations": [{"table": "billing.invoices"}, {"table": "billing.clients"}],
                "executed_sql": SQL_VENCIDAS,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Faturas vencidas", "Overdue invoices"), "vencidas_n"),
                    tile(L("Por receber", "Outstanding"), "vencidas_eur", "eur"),
                ],
            },
            {
                "position": 6,
                "is_suggested": False,
                "question": L("Como evoluiu a faturação ao longo do ano?",
                              "How has billing trended over the year?"),
                "answer_markdown": L(
                    "**Mês a mês, sobre faturas emitidas.** Numa consultora esta curva anda meio "
                    "trimestre atrás da entrega — o trabalho faz-se num mês e fatura-se noutro.\n\n"
                    "É por isso que a faturação sozinha é um mau indicador de saúde: mede o "
                    "passado com atraso.",
                    "**Month by month, on issued invoices.** In a consultancy this curve runs half "
                    "a quarter behind delivery — the work happens one month and is invoiced "
                    "another.\n\n"
                    "Which is why billing on its own is a poor health indicator: it measures the "
                    "past, late."),
                "citations": [{"table": "billing.invoices"}],
                "executed_sql": SQL_SERIE_FATURA,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Faturado no período", "Invoiced in the period"), "faturado", "eur"),
                    tile(L("Horas faturáveis", "Billable hours"), "util_global", "pct"),
                ],
            },
        ],
    }


def main() -> int:
    doc = json.loads(ALVO.read_text(encoding="utf-8"))
    doc["datasets"] = [d for d in doc["datasets"] if d.get("vertical") != "services"]
    doc["datasets"] += [dataset("pt"), dataset("en")]
    ALVO.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("services escrito; datasets no ficheiro:", len(doc["datasets"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
