# -*- coding: utf-8 -*-
"""As demonstrações sectoriais dentro de um projecto.

Nada aqui toca na base nem na rede. O que se verifica são as decisões
que, quando se partem, se partem em silêncio — e só aparecem com um
cliente à frente do ecrã.
"""

from __future__ import annotations

import decimal

import pytest

from scripts.demo_sectorial import alimentacion, transportes
from scripts.demo_sectorial.motor import _id
from scripts.demo_sectorial.pecas import Sector

SECTORES: list[Sector] = [transportes.SECTOR, alimentacion.SECTOR]
IDS = [s.chave for s in SECTORES]


@pytest.fixture(params=SECTORES, ids=IDS)
def sector(request) -> Sector:
    return request.param


# ── a grelha ────────────────────────────────────────────────────────


def _rect(w):
    pos, tam = w.geometria()
    return (pos["x"], pos["y"], pos["x"] + tam["width"], pos["y"] + tam["height"])


def test_nenhum_widget_fica_por_cima_de_outro(sector: Sector):
    """O primeiro esboço tinha dois widgets sobrepostos.

    As posições no canvas são livres, e enquanto foram escritas à mão
    qualquer mexida no layout era um exercício de aritmética. As
    ranhuras existem para isso — e isto é o que confirma que existem
    para alguma coisa.
    """
    for pagina in sector.paginas:
        rects = [(w.titulo, _rect(w)) for w in pagina.widgets]
        for i, (t1, (ax1, ay1, ax2, ay2)) in enumerate(rects):
            for t2, (bx1, by1, bx2, by2) in rects[i + 1:]:
                sobrepoe = ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2
                assert not sobrepoe, (
                    f"{pagina.nome}: {t1!r} e {t2!r} ocupam o mesmo sítio"
                )


def test_cada_widget_aponta_a_uma_ligacao_que_existe(sector: Sector):
    for pagina in sector.paginas:
        for w in pagina.widgets:
            assert w.esquema in sector.ligacoes, (
                f"{pagina.nome} / {w.titulo}: ligação {w.esquema!r} não existe"
            )


# ── a decisão que tem de aguentar ───────────────────────────────────


def _esquemas_citados(sql: str, conhecidos: set[str]) -> set[str]:
    return {e for e in conhecidos if f"{e}." in sql}


def test_cada_agente_vive_dentro_de_um_so_esquema(sector: Sector):
    """É a decisão central deste desenho, e a mais fácil de desfazer.

    Uma ligação Postgres tem UM esquema. Um agente apontado à ligação
    `ops` não consegue juntar `fleet` nem `freight` — e se a sua
    pergunta pedir essa junção, ele não falha com erro: responde mal, ao
    vivo, à frente do cliente.

    ── A primeira versão deste teste não servia para nada ──────────

    Procurava nomes de tabelas no texto do `foco`. Mas um `foco` é uma
    pergunta em castelhano escrita para uma pessoa — nenhum agente real
    nomeia tabelas. O teste passava sempre, com qualquer agente,
    incluindo um que pedisse uma junção impossível. Só falhava com um
    agente inventado de propósito para o fazer falhar, que é a definição
    de um teste que fixa o código em vez do comportamento.

    Agora cada agente declara as tabelas de que precisa, e é essa
    declaração que se verifica. Continua a ser preciso que quem escreve
    o agente seja honesto na declaração — mas isso é uma linha visível
    na revisão, em vez de uma suposição invisível.
    """
    por_sufixo = {k: esq for k, (_, esq, _) in sector.ligacoes.items()}
    for ag in sector.agentes:
        assert ag.tabelas, (
            f"agente {ag.nome!r} não declara as tabelas de que precisa — "
            "sem isso não há como saber se a ligação lhe chega"
        )
        seu = por_sufixo[ag.esquema]
        for tabela in ag.tabelas:
            assert "." in tabela, f"{ag.nome!r}: {tabela!r} devia vir com esquema"
            esquema = tabela.split(".", 1)[0]
            assert esquema == seu, (
                f"agente {ag.nome!r} está ligado a {seu!r} e precisa de "
                f"{tabela!r} — não a consegue ler."
            )


def test_os_paineis_e_so_eles_atravessam_esquemas(sector: Sector):
    """O contrapeso do teste acima.

    Se nenhum painel juntar esquemas, a demonstração perdeu o argumento
    que a justifica: a resposta que o cliente não tem é precisamente a
    que mora em três sistemas ao mesmo tempo.
    """
    esquemas = {esq for _, esq, _ in sector.ligacoes.values()}
    atravessam = [
        w.titulo
        for pagina in sector.paginas
        for w in pagina.widgets
        if len(_esquemas_citados(w.sql, esquemas)) > 1
    ]
    assert atravessam, (
        "nenhum widget junta dois esquemas — a demonstração ficou a mostrar "
        "o que cada sistema já mostra sozinho"
    )


# ── o conteúdo ──────────────────────────────────────────────────────


def test_o_sector_tem_o_que_foi_pedido(sector: Sector):
    assert 3 <= len(sector.paginas) <= 4, "pediram-se três a quatro painéis"
    assert len(sector.agentes) == 5, "pediram-se cinco agentes"
    for pagina in sector.paginas:
        assert pagina.widgets, f"{pagina.nome} está vazia"


def test_cada_kpi_pede_um_numero_so(sector: Sector):
    """Um `SELECT` com várias colunas enche o cartão com a primeira.

    Não dá erro — dá o número errado, com ar de certo.
    """
    for pagina in sector.paginas:
        for w in pagina.widgets:
            if w.tipo != "kpi":
                continue
            dados = w.dados([{"v": 42}])
            assert dados["value"] == 42
            assert dados["config"]["label"], f"{w.titulo} sem legenda"


def test_o_mapeamento_do_grafico_usa_colunas_que_a_consulta_devolve(sector: Sector):
    """O `ChartWidget` recusa desenhar se `mapping.x`/`y` não existirem.

    Recusa em silêncio, com uma nota na consola do browser que ninguém
    tem aberta numa reunião. Aqui confirma-se contra os nomes que o SQL
    declara com `AS`.
    """
    for pagina in sector.paginas:
        for w in pagina.widgets:
            if w.tipo != "chart":
                continue
            mapping = w.dados([{}])["mapping"]
            for eixo in ("x", "y"):
                coluna = mapping[eixo]
                assert f"AS {coluna}" in w.sql or f'AS "{coluna}"' in w.sql, (
                    f"{pagina.nome} / {w.titulo}: o eixo {eixo} é {coluna!r} e a "
                    "consulta não devolve nenhuma coluna com esse nome"
                )


# ── identidade ──────────────────────────────────────────────────────


def test_os_identificadores_nao_mudam_entre_corridas():
    """É o que torna o semeador repetível.

    Se mudarem, correr outra vez cria um segundo projecto com o mesmo
    nome em vez de actualizar o primeiro — e numa base de cliente isso
    não se desfaz com um botão.
    """
    assert _id("transportes", "space") == _id("transportes", "space")
    assert _id("transportes", "space") != _id("transportes", "crew")
    assert _id("transportes", "space") != _id("outro", "space")


# ── a conversão de tipos ────────────────────────────────────────────


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        (decimal.Decimal("1.50"), 1.5),
        (decimal.Decimal("69830"), 69830),
        # `ROUND()` sobre um bigint devolve `double precision`, não
        # `numeric`. Sem este caso a coluna "Km" de um quadro saía
        # `69830.0` — não está errada, e fica mal.
        (69830.0, 69830),
        (1.4999, 1.5),
        (True, True),
        (None, None),
        ("Lisboa - Madrid", "Lisboa - Madrid"),
    ],
)
def test_a_conversao_de_valores_para_json(entrada, esperado):
    from scripts.demo_sectorial.motor import _converter

    assert _converter(entrada) == esperado
    # `True == 1` em Python: sem comparar o tipo, o caso do booleano
    # passaria com a conversão a transformá-lo em inteiro.
    assert type(_converter(entrada)) is type(esperado)
