"""A lista de agentes tem de trazer os sinais de vida.

**O defeito.** Todos os agentes diziam «A correr, mas ainda nao encontrou
nada» — incluindo um com 22 descobertas no feed, do mesmo projeto.

A app nao estava enganada: o servidor nunca lhe mandou o campo. As tres
chaves — `last_finding_at`, `last_finding_title`, `last_run_status` — nao
vinham a `null`; **nao vinham de todo**.

O repositorio preenche-as na listagem (`_anexar_sinais_de_vida`) e o
`AgentResponse` declara-as. O `AgentListResponse` — que e o que a rota da
LISTA usa, e a lista e o que a app le — nao as declarava, e o Pydantic
deita fora o que nao declara.

**E o mesmo erro que ja tinha acontecido no mesmo ficheiro**, com o
`conversation_id`, e que tem um comentario de sete linhas a descreve-lo:
«Pus isto no `AgentResponse` e promovi, e o botao continuou a nao aparecer:
o ecra dos agentes le a LISTA». Um comentario avisa quem o le. Este teste
impede.
"""

import pytest

from src.schemas.agent import AgentListResponse, AgentResponse

#: Os campos que a app precisa para dizer como vai um agente. Se um deles
#: existir no detalhe e faltar na lista, o ecra mente.
SINAIS_DE_VIDA = ("last_finding_at", "last_finding_title", "last_run_status")


@pytest.mark.parametrize("campo", SINAIS_DE_VIDA)
def test_a_lista_declara_o_campo(campo):
    assert campo in AgentListResponse.model_fields, (
        f"{campo} falta no AgentListResponse — o Pydantic deita fora o que "
        "nao declara, e o ecra dos agentes le a LISTA"
    )


def test_a_lista_nao_fica_atras_do_detalhe():
    """Uma varredura, em vez de uma lista que envelhece.

    E assim que este defeito nasce: acrescenta-se um campo ao detalhe e
    ninguem se lembra de que ha dois schemas. Ja aconteceu duas vezes.

    Os campos so do detalhe estao nomeados de proposito — quem acrescentar um
    terceiro tem de vir aqui dizer porque.
    """
    SO_DO_DETALHE = {
        # Pesados: a listagem nao os carrega de proposito, para nao esgotar a
        # pousada de ligacoes (ver o comentario no `AgentListResponse`).
        "findings",
        # A mascara de conteudo (Opcao B): so faz sentido ao lado dos achados,
        # e a lista nao os traz. Ver o comentario no `AgentResponse`.
        "findings_restricted",
        # Só fazem sentido a olhar para UM agente.
        "question",
        "instructions",
        "updated_at",
        "created_by",
        "consecutive_failures",
        "conversation_count",
    }
    do_detalhe = set(AgentResponse.model_fields)
    da_lista = set(AgentListResponse.model_fields)
    em_falta = do_detalhe - da_lista - SO_DO_DETALHE
    assert em_falta == set(), (
        f"campos no detalhe e nao na lista: {sorted(em_falta)} — ou entram na "
        "lista, ou entram no SO_DO_DETALHE com uma razao"
    )
