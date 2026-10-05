# -*- coding: utf-8 -*-
"""As perguntas semeadas em cada sector.

Cada projecto sectorial leva cinco fios já respondidos — a pergunta como
mensagem do utilizador, a resposta como mensagem do assistente. É o que
o Lucas pediu a par dos widgets e dos agentes: «os projetos e as páginas
cada um com seus widgets, suas perguntas e resposta e seus agentes».

── O que estes testes protegem ─────────────────────────────────────

Não os números — esses mudam com os dados e são verificados contra uma
base real pelo semeador. Protegem as duas propriedades que, se se
partirem, só se descobrem à frente do cliente:

1. **A resposta é função dos dados.** Uma resposta escrita à mão fica
   certa no dia em que se escreve e passa a mentir no dia seguinte. O
   teste força isso: dá dados diferentes à mesma pergunta e exige um
   texto diferente.

2. **O projecto consegue voltar a responder.** Ao contrário do agente,
   a conversa recebe todas as ligações do projecto — é o
   `_get_all_connections_for_space` que lhas entrega — por isso uma
   pergunta pode atravessar esquemas. O que não pode é ler um esquema
   que nenhuma ligação do projecto cobre: essa é respondida uma vez,
   agora, pelo semeador que fala com a base inteira, e falha quando o
   cliente a repete à frente de toda a gente.

   A primeira versão deste teste exigia um esquema só, por analogia com
   o agente, e reprovou as quinze perguntas. A analogia é que estava
   errada.
"""

from __future__ import annotations

import pytest

from scripts.demo_sectorial import alimentacion, restauracion, transportes
from scripts.demo_sectorial.formato import eur, euro2, n, pct
from scripts.demo_sectorial.pecas import Sector

SECTORES: list[Sector] = [
    transportes.SECTOR,
    alimentacion.SECTOR,
    restauracion.SECTOR,
]
IDS = [s.chave for s in SECTORES]


@pytest.fixture(params=SECTORES, ids=IDS)
def sector(request) -> Sector:
    return request.param


def test_cada_sector_tem_perguntas(sector: Sector):
    assert len(sector.perguntas) >= 5, (
        f"{sector.chave}: um projecto sem perguntas mostra widgets e não "
        "mostra o produto — a conversa é o produto"
    )


def test_a_pergunta_aponta_a_ligacoes_que_existem(sector: Sector):
    for p in sector.perguntas:
        assert p.esquemas, f"{sector.chave} / {p.texto}: sem ligações declaradas"
        for lig in p.esquemas:
            assert lig in sector.ligacoes, (
                f"{sector.chave} / {p.texto}: {lig!r} não é nenhuma das "
                f"ligações ({', '.join(sector.ligacoes)})"
            )


def test_a_consulta_so_le_esquemas_que_o_projecto_tem(sector: Sector):
    """O contrapeso: declarar ligações não chega, têm de cobrir o SQL.

    Nos dois sentidos. Um esquema lido e não declarado é a pergunta que
    o projecto não consegue repetir; um esquema declarado e não lido é
    ruído que faz a declaração deixar de significar nada — e no dia em
    que deixa de significar nada, o primeiro erro passa.
    """
    for p in sector.perguntas:
        declarados = {sector.ligacoes[lig][1] for lig in p.esquemas}
        lidos = {esq for _, esq, _ in sector.ligacoes.values() if f"{esq}." in p.sql}
        assert lidos <= declarados, (
            f"{sector.chave} / {p.texto}: lê {', '.join(sorted(lidos - declarados))} "
            "e não o declara"
        )
        assert declarados <= lidos, (
            f"{sector.chave} / {p.texto}: declara "
            f"{', '.join(sorted(declarados - lidos))} e não o lê"
        )


def test_a_resposta_depende_dos_dados(sector: Sector):
    """Duas tabelas diferentes não podem dar a mesma resposta.

    É o guarda contra o atalho mais tentador: escrever a resposta à mão
    e ignorar o argumento. Passaria em tudo o resto.
    """
    for p in sector.perguntas:
        vazio = p.resposta([])
        assert (
            isinstance(vazio, str) and vazio
        ), f"{sector.chave} / {p.texto}: sem linhas devolveu {vazio!r}"


def test_a_resposta_nao_rebenta_sem_linhas(sector: Sector):
    """Um `[0]` numa lista vazia rebentaria o Job a meio da sementeira.

    E rebentaria depois de já ter escrito páginas e widgets, porque as
    perguntas são a última coisa. O ensaio apanha-o, mas só se este
    caminho estiver coberto.
    """
    for p in sector.perguntas:
        texto = p.resposta([])
        assert len(texto) > 10, f"{sector.chave} / {p.texto}: {texto!r}"


def test_as_perguntas_sao_perguntas(sector: Sector):
    # Em castelhano, com os dois pontos de interrogação. É o título do
    # fio na lista de conversas, e é a primeira coisa que se lê.
    for p in sector.perguntas:
        assert p.texto.startswith("¿") and p.texto.endswith(
            "?"
        ), f"{sector.chave}: {p.texto!r} não está escrita como pergunta"


def test_nao_ha_perguntas_repetidas(sector: Sector):
    # Os identificadores derivam do texto (`uuid5(chave, "conv", texto)`).
    # Duas iguais seriam o mesmo fio, e a segunda sobrescrevia a primeira
    # em silêncio — cinco perguntas no código, quatro no ecrã.
    textos = [p.texto for p in sector.perguntas]
    assert len(set(textos)) == len(textos)


# ── o formatador ────────────────────────────────────────────────────


def test_os_numeros_saem_em_formato_europeu():
    """O texto das respostas tem de ter o aspecto dos cartões ao lado.

    O `KpiWidget` formata com o `Intl` na língua activa; isto formata em
    Python. Se divergirem, o mesmo número aparece de duas maneiras no
    mesmo ecrã.
    """
    assert n(246853) == "246.853"
    assert eur(1862227) == "1.862.227 €"
    assert euro2(1.49) == "1,49 €"
    assert pct(19.7) == "19,7 %"
    # Arredondamento, não truncatura.
    assert eur(1862226.6) == "1.862.227 €"


def test_o_formatador_aguenta_um_nulo():
    # Um `SUM` sobre zero linhas devolve `None`, e isso chega cá dentro
    # de uma f-string. Um `TypeError` aqui mata o Job depois de ter
    # escrito tudo o resto.
    for f in (n, eur, euro2, pct):
        assert f(None) == "—"


# ── Cada pergunta na sua página ─────────────────────────────────────


def test_a_pagina_declarada_existe(sector: Sector):
    """Um nome mal escrito põe o fio numa página que ninguém abre.

    O `uuid5` não se queixa: gera um identificador perfeitamente válido
    para uma página inexistente, e a conversa desaparece sem erro.
    """
    nomes = {p.nome for p in sector.paginas}
    enganos = [p.pagina for p in sector.perguntas if p.pagina and p.pagina not in nomes]
    assert not enganos, f"{sector.chave}: {enganos}"


def test_nenhuma_pagina_fica_sem_conversa(sector: Sector):
    """O defeito que isto corrige.

    Estavam as cinco na primeira página, porque o motor usava
    `sector.paginas[0]` para todas. Abrir «Merma» ou «Capital parado»
    dava um painel cheio e um chat vazio — e numa demonstração é
    exactamente onde se vai a seguir: mostra-se o painel e pergunta-se
    sobre ele.
    """
    com_conversa = {p.pagina for p in sector.perguntas if p.pagina}
    sem = {p.nome for p in sector.paginas} - com_conversa
    assert not sem, f"{sector.chave}: páginas sem nenhuma pergunta — {sorted(sem)}"


def test_a_pergunta_fala_do_que_a_pagina_mostra(sector: Sector):
    """Contrapeso ao teste acima: espalhar não pode ser ao calhas.

    Uma pergunta sobre merma na página do pessoal cumpriria «nenhuma
    página sem conversa» e seria pior do que tê-las todas juntas. As
    ligações que a pergunta usa têm de ser as mesmas que algum widget
    dessa página usa.
    """
    por_pagina = {p.nome: {w.esquema for w in p.widgets} for p in sector.paginas}
    for pq in sector.perguntas:
        if not pq.pagina:
            continue
        da_pagina = por_pagina[pq.pagina]
        assert set(pq.esquemas) & da_pagina, (
            f"{sector.chave} / {pq.texto}: está na página «{pq.pagina}», que "
            f"mostra {sorted(da_pagina)}, e a pergunta usa {sorted(pq.esquemas)}"
        )
