"""Conteúdo dos passos 1 e 2 do fluxo da demo (FE-06).

A regra que estes testes protegem é a única que decide se o fluxo
funciona: **cada passo pede uma coisa pequena e devolve imediatamente
uma coisa concreta.** Um passo que pede sem devolver é um imposto, e o
visitante sai.

Foi a lição da v1: o conteúdo estava certo — insight real, números
reais, SQL à vista — mas servido numa página parada. Sem progressão e
sem participação, ler um cartão não é usar um produto.
"""

from __future__ import annotations

import pytest

from src.services import demo_flow_service as flow

MARKETING_VAZIO = (
    "novo petróleo",
    "revolucionar",
    "sinergia",
    "lorem ipsum",
    "transformação digital",
    "próximo nível",
)


# ─── passo 1 ────────────────────────────────────────────────────────


def test_todas_as_verticais_tem_gancho():
    """Uma opção sem gancho é um passo que pede sem devolver."""
    verticals = flow.list_verticals()

    assert verticals, "sem verticais o passo 1 não tem nada para mostrar"
    for v in verticals:
        assert v["hook_markdown"].strip(), v["id"]


def test_ganchos_sao_concretos_e_nao_marketing():
    """'Os dados são o novo petróleo' não faz ninguém continuar.
    'Uma conta que paga 40 lugares e usa 18' faz."""
    for v in flow.list_verticals():
        low = v["hook_markdown"].lower()
        for termo in MARKETING_VAZIO:
            assert termo not in low, f"{v['id']}: {termo!r}"


def test_ganchos_tem_substancia():
    """Uma frase solta não convence ninguém a dar o passo seguinte —
    o gancho tem de explicar *porque* é que aquilo acontece."""
    for v in flow.list_verticals():
        assert len(v["hook_markdown"]) > 180, f"{v['id']} é curto de mais"


def test_as_quatro_verticais_do_desenho_existem():
    ids = {v["id"] for v in flow.list_verticals()}

    assert {"saas", "distribution", "services", "industry"} <= ids


# ─── passo 2 ────────────────────────────────────────────────────────


def test_nao_sei_bem_e_opcao_de_primeira_classe():
    """Obrigar um decisor a fingir que sabe onde vivem os dados da
    empresa é a forma mais rápida de o perder."""
    ids = {s["id"] for s in flow.list_sources()}

    assert "unknown" in ids


def test_nao_sei_bem_acolhe_em_vez_de_corrigir():
    res = flow.unlocked_questions(source_ids=["unknown"])

    assert "problema" in res["intro_markdown"].lower()
    assert res["questions"], "mesmo sem saber a fonte, tem de receber perguntas"


def test_sempre_tres_perguntas():
    """Um ecrã que promete três e mostra uma parece avariado."""
    for ids in ([], ["postgres"], ["sheets"], ["postgres", "sheets", "bigquery"], ["inexistente"]):
        res = flow.unlocked_questions(source_ids=ids)
        assert len(res["questions"]) == flow.UNLOCKED_LIMIT, ids


def test_perguntas_refletem_a_fonte_escolhida():
    postgres = flow.unlocked_questions(source_ids=["postgres"])["questions"]
    databricks = flow.unlocked_questions(source_ids=["databricks"])["questions"]

    assert postgres != databricks, "a escolha tem de mudar o que ele vê"


def test_duas_fontes_ambas_contam():
    """Quem escolheu Postgres e Excel deve ver que ambas contam, não
    três perguntas de Postgres."""
    combinado = flow.unlocked_questions(source_ids=["postgres", "sheets"])["questions"]
    so_postgres = flow.unlocked_questions(source_ids=["postgres"])["questions"]

    assert combinado != so_postgres


def test_nunca_ha_perguntas_repetidas():
    res = flow.unlocked_questions(source_ids=["postgres", "postgres", "mysql"])

    assert len(set(res["questions"])) == len(res["questions"])


def test_a_objeccao_principal_e_respondida_sempre():
    """'Vão ter de mover os meus dados?' é a primeira pergunta de
    qualquer responsável de TI, e a resposta tem de estar à vista antes
    de ele a fazer."""
    res = flow.unlocked_questions(source_ids=["postgres"])

    assert "sem mover nada" in res["intro_markdown"].lower()


# ─── robustez ───────────────────────────────────────────────────────


def test_fontes_desconhecidas_nao_rebentam():
    """Um cliente antigo com um id que já não existe não pode partir o
    passo 2."""
    res = flow.unlocked_questions(source_ids=["fonte-que-nao-existe", None, ""])

    assert len(res["questions"]) == flow.UNLOCKED_LIMIT


@pytest.mark.parametrize("bad", [None, []])
def test_sem_escolha_nenhuma_ainda_devolve(bad):
    """Quem carrega em avançar sem escolher nada tem de ver alguma
    coisa — saltar não pode ser um beco."""
    assert flow.unlocked_questions(source_ids=bad)["questions"]
