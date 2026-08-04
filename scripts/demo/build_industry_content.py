# -*- coding: utf-8 -*-
"""Conteúdo curado do sector Indústria / Produção.

Mesma razão dos outros dois: SQL partilhado, texto por idioma.

    python scripts/demo/build_industry_content.py
    python scripts/curate_demo_content.py --verify-sql --apply
"""

from __future__ import annotations

import json
from pathlib import Path

ALVO = Path(__file__).resolve().parents[2] / "scripts" / "demo" / "curated_content.json"

# ── SQL ──────────────────────────────────────────────────────────────

SQL_REFUGO = """SELECT m.code, m.line, m.installed_year,
       SUM(s.units) AS scrap_units,
       SUM(o.planned_units) AS planned_units,
       ROUND(100.0 * SUM(s.units) / NULLIF(SUM(o.planned_units), 0), 2) AS scrap_pct
FROM quality.scrap s
JOIN production.orders o ON o.id = s.order_id
JOIN plant.machines m ON m.id = o.machine_id
GROUP BY m.code, m.line, m.installed_year
ORDER BY scrap_pct DESC"""

SQL_MOTIVOS = """SELECT s.reason, SUM(s.units) AS units, COUNT(*) AS occurrences
FROM quality.scrap s
GROUP BY s.reason
ORDER BY units DESC"""

SQL_PARAGENS = """SELECT m.code, m.line,
       COUNT(*) AS stoppages,
       ROUND(SUM(st.minutes) / 60.0, 1) AS hours_lost,
       ROUND(AVG(st.minutes)) AS avg_minutes
FROM maintenance.stoppages st
JOIN plant.machines m ON m.id = st.machine_id
WHERE NOT st.planned
GROUP BY m.code, m.line
ORDER BY hours_lost DESC"""

SQL_TURNOS = """SELECT o.shift,
       COUNT(*) AS orders,
       SUM(o.planned_units) AS planned,
       SUM(o.good_units) AS good,
       ROUND(100.0 * SUM(o.good_units) / NULLIF(SUM(o.planned_units), 0), 1) AS yield_pct
FROM production.orders o
GROUP BY o.shift
ORDER BY yield_pct"""

SQL_LINHAS = """SELECT m.line,
       COUNT(DISTINCT m.id) AS machines,
       SUM(o.good_units) AS good_units,
       ROUND(100.0 * SUM(o.good_units) / NULLIF(SUM(o.planned_units), 0), 1) AS yield_pct
FROM production.orders o
JOIN plant.machines m ON m.id = o.machine_id
GROUP BY m.line
ORDER BY yield_pct DESC"""

SQL_SERIE_REFUGO = """SELECT DATE_TRUNC('month', o.produced_on)::date AS t,
       ROUND(100.0 * SUM(s.units) / NULLIF(SUM(o.planned_units), 0), 2) AS v
FROM production.orders o
LEFT JOIN quality.scrap s ON s.order_id = o.id
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_PARAGENS = """SELECT DATE_TRUNC('month', st.started_at)::date AS t,
       ROUND(SUM(st.minutes) / 60.0, 1) AS v
FROM maintenance.stoppages st
WHERE NOT st.planned
GROUP BY 1 ORDER BY 1"""

SQL_SERIE_TURNOS = """SELECT o.shift AS t,
       ROUND(100.0 * SUM(o.good_units) / NULLIF(SUM(o.planned_units), 0), 1) AS v
FROM production.orders o
GROUP BY o.shift
ORDER BY v"""

SQL_PRODUCAO = """SELECT DATE_TRUNC('month', o.produced_on)::date AS month,
       SUM(o.planned_units) AS planned,
       SUM(o.good_units) AS good,
       ROUND(100.0 * SUM(o.good_units) / NULLIF(SUM(o.planned_units), 0), 1) AS yield_pct
FROM production.orders o
GROUP BY 1 ORDER BY 1"""

SQL_MAQUINA_VELHA = """SELECT m.code, m.installed_year, m.nominal_rate,
       ROUND(100.0 * SUM(o.good_units) / NULLIF(SUM(o.planned_units), 0), 1) AS yield_pct,
       ROUND(SUM(st.minutes) / 60.0, 1) AS unplanned_hours
FROM plant.machines m
JOIN production.orders o ON o.machine_id = m.id
LEFT JOIN maintenance.stoppages st ON st.machine_id = m.id AND NOT st.planned
GROUP BY m.code, m.installed_year, m.nominal_rate
ORDER BY m.installed_year"""

V = {
    "maquina_pior": (
        "SELECT m.code FROM quality.scrap s JOIN production.orders o ON o.id = s.order_id "
        "JOIN plant.machines m ON m.id = o.machine_id GROUP BY m.code "
        "ORDER BY SUM(s.units)::numeric / NULLIF(SUM(o.planned_units), 0) DESC LIMIT 1"
    ),
    "refugo_pior_pct": (
        "SELECT ROUND(MAX(x.p), 2) FROM (SELECT SUM(s.units) * 100.0 / NULLIF(SUM(o.planned_units), 0) AS p "
        "FROM quality.scrap s JOIN production.orders o ON o.id = s.order_id "
        "GROUP BY o.machine_id) x"
    ),
    "refugo_resto_pct": (
        "SELECT ROUND(AVG(x.p), 2) FROM (SELECT SUM(s.units) * 100.0 / NULLIF(SUM(o.planned_units), 0) AS p "
        "FROM quality.scrap s JOIN production.orders o ON o.id = s.order_id "
        "GROUP BY o.machine_id ORDER BY p DESC OFFSET 1) x"
    ),
    "motivo_top": "SELECT reason FROM quality.scrap GROUP BY reason ORDER BY SUM(units) DESC LIMIT 1",
    "paragens_horas": (
        "SELECT ROUND(SUM(minutes) / 60.0, 1) FROM maintenance.stoppages WHERE NOT planned"
    ),
    "paragens_pior": (
        "SELECT m.code FROM maintenance.stoppages st JOIN plant.machines m ON m.id = st.machine_id "
        "WHERE NOT st.planned GROUP BY m.code ORDER BY SUM(st.minutes) DESC LIMIT 1"
    ),
    "paragens_pior_horas": (
        "SELECT ROUND(MAX(x.h), 1) FROM (SELECT SUM(minutes) / 60.0 AS h FROM maintenance.stoppages "
        "WHERE NOT planned GROUP BY machine_id) x"
    ),
    "turno_pior": (
        "SELECT shift FROM production.orders GROUP BY shift "
        "ORDER BY SUM(good_units)::numeric / NULLIF(SUM(planned_units), 0) LIMIT 1"
    ),
    "turno_pior_pct": (
        "SELECT ROUND(MIN(x.p), 1) FROM (SELECT SUM(good_units) * 100.0 / NULLIF(SUM(planned_units), 0) AS p "
        "FROM production.orders GROUP BY shift) x"
    ),
    "turno_melhor_pct": (
        "SELECT ROUND(MAX(x.p), 1) FROM (SELECT SUM(good_units) * 100.0 / NULLIF(SUM(planned_units), 0) AS p "
        "FROM production.orders GROUP BY shift) x"
    ),
    "rendimento_global": (
        "SELECT ROUND(100.0 * SUM(good_units) / NULLIF(SUM(planned_units), 0), 1) FROM production.orders"
    ),
    "unidades_boas": "SELECT SUM(good_units) FROM production.orders",
    "refugo_unidades": "SELECT COALESCE(SUM(units), 0) FROM quality.scrap",
    "maquina_mais_velha": "SELECT code FROM plant.machines ORDER BY installed_year LIMIT 1",
    "ano_mais_velha": "SELECT MIN(installed_year) FROM plant.machines",
    "linha_melhor": (
        "SELECT m.line FROM production.orders o JOIN plant.machines m ON m.id = o.machine_id "
        "GROUP BY m.line ORDER BY SUM(o.good_units)::numeric / NULLIF(SUM(o.planned_units), 0) DESC LIMIT 1"
    ),
}

FONTES = [
    {"table": "production.orders", "description": "Planeado contra bom, por turno"},
    {"table": "quality.scrap", "description": "Refugo e motivo"},
    {"table": "maintenance.stoppages", "description": "Paragens planeadas e não planeadas"},
    {"table": "plant.machines", "description": "Linha, ano e cadência nominal"},
]


def tile(rotulo, chave, formato=None):
    t = {"label": rotulo, "value_sql": V[chave]}
    if formato:
        t["format"] = formato
    return t


def dataset(locale):
    pt = locale == "pt"
    L = lambda a, b: a if pt else b  # noqa: E731

    return {
        "vertical": "industry",
        "locale": locale,
        "is_default": False,
        "name": L("Fábrica Ribatejo — 9 máquinas, 3 linhas",
                  "Ribatejo Plant — 9 machines, 3 lines"),
        "description": L(
            "Produção em três turnos, com registo de refugo por motivo e paragens por máquina.",
            "Three-shift production, with scrap by reason and stoppages by machine."),
        "connection_ref": L("Demo — Indústria", "Demo — Industry"),
        "insight": {
            "severity": "scrap_concentration",
            "severity_level": "warning",
            "agent_name": L("Qualidade", "Quality"),
            "title": L("Uma máquina faz quase todo o refugo, e é a mais velha",
                       "One machine makes nearly all the scrap, and it's the oldest"),
            "summary": L(
                "A taxa média de refugo da fábrica não diz nada, porque não é uma média — é uma "
                "máquina. Separada das outras, a diferença é de ordem de grandeza, e o motivo "
                "registado é sempre o mesmo.\n\n"
                "É essa concentração que transforma \"temos um problema de qualidade\" em \"temos "
                "um problema na M-07\". A primeira frase não tem dono; a segunda tem orçamento.",
                "The plant's average scrap rate says nothing, because it isn't an average — it's "
                "one machine. Separated from the rest the difference is an order of magnitude, "
                "and the logged reason is always the same one.\n\n"
                "That concentration is what turns \"we have a quality problem\" into \"we have an "
                "M-07 problem\". The first sentence has no owner; the second has a budget."),
            "stat_tiles": [
                tile(L("Máquina", "Machine"), "maquina_pior"),
                tile(L("Refugo dela", "Its scrap rate"), "refugo_pior_pct", "pct"),
                tile(L("Média das outras", "The others' average"), "refugo_resto_pct", "pct"),
            ],
            "sources": FONTES,
            "executed_sql": SQL_REFUGO,
            "series_sql": SQL_SERIE_REFUGO,
        },
        "extra_insights": [
            {
                "severity": "unplanned_downtime",
                "severity_level": "warning",
                "agent_name": L("Manutenção", "Maintenance"),
                "title": L("Horas perdidas em paragens que ninguém planeou",
                           "Hours lost to stoppages nobody planned"),
                "summary": L(
                    "Paragem planeada é custo; paragem não planeada é custo mais surpresa — e a "
                    "surpresa é o que estraga o plano de produção da semana inteira.\n\n"
                    "O agente separa as duas e soma só as segundas. A conta é simples e ninguém a "
                    "faz todos os meses, porque vive num sistema diferente do da produção.",
                    "Planned downtime is a cost; unplanned downtime is a cost plus a surprise — "
                    "and the surprise is what wrecks the whole week's production plan.\n\n"
                    "The agent separates the two and adds up only the second. The arithmetic is "
                    "simple and nobody does it monthly, because it lives in a different system "
                    "from production."),
                "stat_tiles": [
                    tile(L("Horas perdidas", "Hours lost"), "paragens_horas"),
                    tile(L("Pior máquina", "Worst machine"), "paragens_pior"),
                    tile(L("Horas só dela", "Hours on that one alone"), "paragens_pior_horas"),
                ],
                "sources": [FONTES[2], FONTES[3]],
                "executed_sql": SQL_PARAGENS,
                "series_sql": SQL_SERIE_PARAGENS,
            },
            {
                "severity": "shift_gap",
                "severity_level": "info",
                "agent_name": L("Turnos", "Shifts"),
                "title": L("Um turno rende menos com o mesmo equipamento",
                           "One shift yields less on the same equipment"),
                "summary": L(
                    "As máquinas são as mesmas, as ordens são as mesmas, o rendimento não é. "
                    "Quando o equipamento é constante e o resultado muda, a variável é humana — "
                    "formação, dotação, ou o apoio que existe às três da manhã e não existe às "
                    "onze.\n\n"
                    "Não diz o que fazer. Diz onde olhar, que é mais do que uma média por fábrica "
                    "alguma vez disse.",
                    "The machines are the same, the orders are the same, the yield isn't. When "
                    "the equipment is constant and the result changes, the variable is human — "
                    "training, staffing, or the support that exists at eleven and doesn't at "
                    "three in the morning.\n\n"
                    "It doesn't say what to do. It says where to look, which is more than a "
                    "plant-wide average has ever said."),
                "stat_tiles": [
                    tile(L("Turno com menor rendimento", "Lowest-yield shift"), "turno_pior"),
                    tile(L("Rendimento dele", "Its yield"), "turno_pior_pct", "pct"),
                    tile(L("O melhor turno", "The best shift"), "turno_melhor_pct", "pct"),
                ],
                "sources": [FONTES[0]],
                "executed_sql": SQL_TURNOS,
                "series_sql": SQL_SERIE_TURNOS,
            },
        ],
        "qas": [
            {
                "position": 0,
                "is_suggested": True,
                "question": L("Que máquina está a fazer mais refugo?",
                              "Which machine is producing the most scrap?"),
                "answer_markdown": L(
                    "**Uma só, e com folga.** A taxa dela está numa ordem de grandeza diferente da "
                    "média das restantes, e é também a mais antiga do parque.\n\n"
                    "Isto muda a conversa: com uma taxa média de fábrica, a resposta é \"temos de "
                    "melhorar a qualidade\", que não tem dono. Com a máquina identificada, é uma "
                    "decisão de manutenção ou de substituição, com um número ao lado.\n\n"
                    "Cruza o refugo registado pela qualidade com as ordens de produção — dois "
                    "sistemas, uma resposta.",
                    "**One, by a distance.** Its rate is an order of magnitude away from the "
                    "average of the rest, and it's also the oldest machine on the floor.\n\n"
                    "That changes the conversation: with a plant-wide average, the answer is "
                    "\"we need to improve quality\", which has no owner. With the machine named, "
                    "it's a maintenance or replacement decision, with a number beside it.\n\n"
                    "It joins scrap logged by quality to the production orders — two systems, one "
                    "answer."),
                "citations": [{"table": "quality.scrap"}, {"table": "production.orders"}],
                "executed_sql": SQL_REFUGO,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Máquina", "Machine"), "maquina_pior"),
                    tile(L("Refugo dela", "Its scrap rate"), "refugo_pior_pct", "pct"),
                    tile(L("Média das outras", "The others' average"), "refugo_resto_pct", "pct"),
                ],
            },
            {
                "position": 1,
                "is_suggested": True,
                "question": L("Quantas horas se perderam em paragens não planeadas?",
                              "How many hours were lost to unplanned stoppages?"),
                "answer_markdown": L(
                    "**Separando as planeadas das não planeadas**, que é o passo que muda o "
                    "número. A manutenção preventiva está no plano; o resto não estava, e é o "
                    "resto que desfaz a semana.\n\n"
                    "Como no refugo, concentra-se numa máquina. É a mesma máquina — o que já não "
                    "é coincidência, é diagnóstico.\n\n"
                    "Sai do registo de paragens, com o motivo e a duração de cada uma.",
                    "**Separating planned from unplanned**, which is the step that changes the "
                    "number. Preventive maintenance is in the plan; the rest wasn't, and it's the "
                    "rest that breaks the week.\n\n"
                    "As with scrap, it concentrates on one machine. It's the same machine — which "
                    "stops being a coincidence and starts being a diagnosis.\n\n"
                    "It comes from the stoppage log, with the reason and duration of each."),
                "citations": [{"table": "maintenance.stoppages"}, {"table": "plant.machines"}],
                "executed_sql": SQL_PARAGENS,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Horas perdidas", "Hours lost"), "paragens_horas"),
                    tile(L("Pior máquina", "Worst machine"), "paragens_pior"),
                    tile(L("Horas só dela", "Hours on that one alone"), "paragens_pior_horas"),
                ],
            },
            {
                "position": 2,
                "is_suggested": True,
                "question": L("Que turno produz menos com o mesmo equipamento?",
                              "Which shift produces less on the same equipment?"),
                "answer_markdown": L(
                    "**A diferença entre o melhor e o pior turno é de vários pontos**, com as "
                    "mesmas máquinas e o mesmo tipo de ordens.\n\n"
                    "Quando o equipamento é constante e o resultado muda, a variável não é "
                    "técnica. Não diz o que fazer — diz onde olhar, e é para isso que serve.\n\n"
                    "Compara unidades boas com unidades planeadas, agrupado por turno.",
                    "**The gap between the best and worst shift is several points**, on the same "
                    "machines and the same kind of orders.\n\n"
                    "When the equipment is constant and the result changes, the variable isn't "
                    "technical. It doesn't say what to do — it says where to look, and that's what "
                    "it's for.\n\n"
                    "It compares good units against planned units, grouped by shift."),
                "citations": [{"table": "production.orders"}],
                "executed_sql": SQL_TURNOS,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Turno com menor rendimento", "Lowest-yield shift"), "turno_pior"),
                    tile(L("Rendimento dele", "Its yield"), "turno_pior_pct", "pct"),
                    tile(L("O melhor turno", "The best shift"), "turno_melhor_pct", "pct"),
                ],
            },
            {
                "position": 3,
                "is_suggested": False,
                "question": L("Quais são os motivos de refugo mais frequentes?",
                              "What are the most common scrap reasons?"),
                "answer_markdown": L(
                    "**Por unidades e por número de ocorrências**, que não dão a mesma ordem: um "
                    "motivo raro que estraga lotes inteiros custa mais do que um frequente que "
                    "estraga peças soltas.\n\n"
                    "Olhar só para a frequência é o erro clássico — leva a equipa a atacar o "
                    "motivo mais visível em vez do mais caro.",
                    "**By units and by number of occurrences**, which don't give the same order: a "
                    "rare reason that ruins whole batches costs more than a frequent one that "
                    "ruins single pieces.\n\n"
                    "Looking only at frequency is the classic mistake — it sends the team after "
                    "the most visible reason instead of the most expensive."),
                "citations": [{"table": "quality.scrap"}],
                "executed_sql": SQL_MOTIVOS,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Motivo com mais unidades", "Reason with most units"), "motivo_top"),
                    tile(L("Unidades rejeitadas", "Units scrapped"), "refugo_unidades"),
                    tile(L("Rendimento global", "Overall yield"), "rendimento_global", "pct"),
                ],
            },
            {
                "position": 4,
                "is_suggested": False,
                "question": L("Que linha de produção rende mais?",
                              "Which production line yields best?"),
                "answer_markdown": L(
                    "**Por rendimento e não por volume.** A linha que produz mais unidades não é "
                    "necessariamente a que desperdiça menos — e é o desperdício que se paga duas "
                    "vezes, no material e no tempo de máquina.\n\n"
                    "Com três linhas, a diferença entre elas é a única referência interna "
                    "honesta que existe.",
                    "**By yield, not by volume.** The line that makes the most units isn't "
                    "necessarily the one that wastes least — and waste is paid for twice, in "
                    "material and in machine time.\n\n"
                    "With three lines, the gap between them is the only honest internal benchmark "
                    "there is."),
                "citations": [{"table": "production.orders"}, {"table": "plant.machines"}],
                "executed_sql": SQL_LINHAS,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Melhor linha", "Best line"), "linha_melhor"),
                    tile(L("Rendimento global", "Overall yield"), "rendimento_global", "pct"),
                    tile(L("Unidades boas", "Good units"), "unidades_boas"),
                ],
            },
            {
                "position": 5,
                "is_suggested": False,
                "question": L("A máquina mais antiga está a compensar?",
                              "Is the oldest machine still worth keeping?"),
                "answer_markdown": L(
                    "**Idade, cadência nominal, rendimento real e horas de paragem, na mesma "
                    "linha.** É a informação de que uma decisão de investimento precisa, e "
                    "costuma estar em quatro sítios diferentes.\n\n"
                    "Uma máquina antiga que produza bem não é problema nenhum. O problema é "
                    "quando a idade aparece ao lado do refugo e das paragens — e aí a conta faz-se "
                    "sozinha.",
                    "**Age, nominal rate, real yield and downtime hours, on the same row.** It's "
                    "the information an investment decision needs, and it usually lives in four "
                    "different places.\n\n"
                    "An old machine that runs well is no problem at all. The problem is when age "
                    "shows up next to scrap and stoppages — and then the arithmetic does itself."),
                "citations": [{"table": "plant.machines"}, {"table": "maintenance.stoppages"}],
                "executed_sql": SQL_MAQUINA_VELHA,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Máquina mais antiga", "Oldest machine"), "maquina_mais_velha"),
                    tile(L("Ano de instalação", "Installed"), "ano_mais_velha"),
                    tile(L("Horas de paragem dela", "Its downtime hours"), "paragens_pior_horas"),
                ],
            },
            {
                "position": 6,
                "is_suggested": False,
                "question": L("Como evoluiu a produção ao longo do ano?",
                              "How has production trended over the year?"),
                "answer_markdown": L(
                    "**Planeado e bom lado a lado, mês a mês.** A distância entre as duas curvas é "
                    "o rendimento, e é aí que se vê se as acções de melhoria deram alguma coisa.\n\n"
                    "Volume sozinho engana: um mês bom em unidades pode ser um mês mau em "
                    "rendimento, e o segundo é que se repete.",
                    "**Planned and good side by side, month by month.** The distance between the "
                    "two curves is the yield, and that's where you see whether the improvement "
                    "actions did anything.\n\n"
                    "Volume alone misleads: a good month in units can be a bad month in yield, and "
                    "it's the second one that repeats."),
                "citations": [{"table": "production.orders"}],
                "executed_sql": SQL_PRODUCAO,
                "chart_spec": None,
                "stat_tiles": [
                    tile(L("Rendimento global", "Overall yield"), "rendimento_global", "pct"),
                    tile(L("Unidades boas", "Good units"), "unidades_boas"),
                    tile(L("Unidades rejeitadas", "Units scrapped"), "refugo_unidades"),
                ],
            },
        ],
    }


def main() -> int:
    doc = json.loads(ALVO.read_text(encoding="utf-8"))
    doc["datasets"] = [d for d in doc["datasets"] if d.get("vertical") != "industry"]
    doc["datasets"] += [dataset("pt"), dataset("en")]
    ALVO.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("industry escrito; datasets no ficheiro:", len(doc["datasets"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
