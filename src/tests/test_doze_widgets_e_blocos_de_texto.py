# -*- coding: utf-8 -*-
"""Doze widgets por página, e três deles em texto.

> «é necessário que os gráficos aqui sejam mais do que seis, tem que ser
>  para ir 12. E tem que haver texto também… como se fosse um
>  infográfico» — Lucas, 06/10/2026

── Porque é que o número está num teste ────────────────────────────

Porque metade de uma página vazia lê-se, numa reunião, como «não há
mais nada para mostrar» — e esse é o argumento todo ao contrário. Seis
widgets num canvas de 1248 píxeis deixavam a metade de baixo em branco.

── E porque é que o texto não é decoração ──────────────────────────

Um painel de números responde «quanto». Não responde «e então?», que é
a frase que se diz em voz alta depois de cada cartão. Sem os blocos de
texto, essa frase vive na cabeça de quem apresenta — e a demonstração
deixa de funcionar sem ele na sala.

── O que isto NÃO verifica ─────────────────────────────────────────

Que o SQL corre. Isso não se verifica aqui: verifica-se contra a base
sintética, e o semeador recusa-se a gravar uma página cuja consulta não
devolva linhas (`SementeiraRecusada`). Os números destes testes são de
forma, não de conteúdo.
"""
from __future__ import annotations

import pytest

from scripts.demo_sectorial import alimentacion, restauracion, transportes
from scripts.demo_sectorial.pecas import AMBAR, AZUL, VERDE, Sector, paragrafos

SECTORES: list[Sector] = [
    transportes.SECTOR,
    alimentacion.SECTOR,
    restauracion.SECTOR,
]
IDS = [s.chave for s in SECTORES]

#: O mínimo pedido. Não é um alvo a bater: é o chão.
MINIMO = 12


@pytest.fixture(params=SECTORES, ids=IDS)
def sector(request) -> Sector:
    return request.param


# ── a contagem ──────────────────────────────────────────────────────


def test_cada_pagina_tem_pelo_menos_doze_widgets(sector: Sector):
    curtas = [
        f"{p.nome} ({len(p.widgets)})" for p in sector.paginas if len(p.widgets) < MINIMO
    ]
    assert not curtas, f"{sector.chave}: páginas com menos de {MINIMO} — {curtas}"


def test_e_pelo_menos_tres_sao_blocos_de_texto(sector: Sector):
    """Sem isto, «doze widgets» cumpria-se com doze gráficos.

    E doze gráficos é mais informação do que seis, não mais sentido.
    """
    for p in sector.paginas:
        textos = [w for w in p.widgets if w.tipo == "text"]
        assert len(textos) >= 3, (
            f"{sector.chave} / {p.nome}: {len(textos)} blocos de texto"
        )


def test_e_ha_variedade_de_desenho(sector: Sector):
    """Doze cartões iguais cansam tanto como seis.

    Pelo menos quatro tipos de peça por página — número, texto, quadro e
    gráfico — e pelo menos três variantes de gráfico diferentes no
    sector. O contrapeso ao «encher a página» é que encher não pode ser
    repetir.
    """
    for p in sector.paginas:
        tipos = {w.tipo for w in p.widgets}
        assert len(tipos) >= 4, f"{sector.chave} / {p.nome}: só {sorted(tipos)}"

    variantes = set()
    for p in sector.paginas:
        for w in p.widgets:
            if w.tipo == "chart":
                dados = w.dados([{}])
                variantes.add(dados.get("type"))
    assert len(variantes) >= 3, f"{sector.chave}: só {sorted(variantes)}"


# ── os blocos de texto ──────────────────────────────────────────────


class _LinhaEspia(dict):
    """Um dicionário que diz que chaves lhe foram pedidas.

    Serve para chamar um `corpo` sem saber o que ele vai ler: devolve um
    valor para qualquer chave e guarda os nomes. Com a lista de chaves
    na mão, chama-se outra vez com valores diferentes — e é isso que
    distingue um texto que depende dos dados de um texto escrito à mão.
    """

    def __init__(self, valor):
        super().__init__()
        self._valor = valor
        self.pedidas: list[str] = []

    def __getitem__(self, chave):
        self.pedidas.append(chave)
        return self._valor

    def get(self, chave, omissao=None):  # noqa: D102
        return self.__getitem__(chave)


def _blocos_de_texto(sector: Sector):
    for p in sector.paginas:
        for w in p.widgets:
            if w.tipo == "text":
                yield p, w


def test_o_texto_e_funcao_dos_dados(sector: Sector):
    """O defeito mais tentador deste ficheiro inteiro.

    «Dois dos camiões não se pagam» fica certo no dia em que se escreve
    e passa a mentir no dia seguinte — e a contradição aparece no MESMO
    ecrã, porque o cartão ao lado conta o mesmo pela consulta.

    O teste chama o mesmo corpo com dois conjuntos de valores e exige
    dois textos diferentes. Uma frase escrita à mão passaria em tudo o
    resto deste ficheiro.
    """
    for p, w in _blocos_de_texto(sector):
        onde = f"{sector.chave} / {p.nome} / {w.titulo}"
        assert w.sql.strip(), f"{onde}: bloco de texto sem SQL"
        um = w.dados([_LinhaEspia(1)])["content"]
        outro = w.dados([_LinhaEspia(2)])["content"]
        assert um != outro, (
            f"{onde}: o texto não muda com os dados — está escrito à mão, e "
            "vai contradizer o cartão ao lado no dia em que os dados mudarem"
        )


def test_o_texto_diz_de_que_fala_na_primeira_linha(sector: Sector):
    """O `TextWidget` desenha-se cru, sem cabeçalho.

    É o único ramo do `widget-container` que não leva `Card` — por isso
    o `titulo` do widget não aparece em lado nenhum, e um bloco sem
    primeira linha de cabeçalho fica a flutuar sem dizer de que fala.
    """
    for p, w in _blocos_de_texto(sector):
        onde = f"{sector.chave} / {p.nome} / {w.titulo}"
        assert w.titulo, f"{sector.chave} / {p.nome}: bloco de texto sem título"
        linhas = [x for x in w.dados([_LinhaEspia(1)])["content"].split("\n") if x.strip()]
        assert linhas, f"{onde}: corpo vazio"
        cabeca = linhas[0]
        # Em maiúsculas, que é o que o distingue do corpo — o widget não
        # tem pesos de letra por parágrafo.
        assert cabeca == cabeca.upper(), f"{onde}: a primeira linha não é cabeçalho"
        assert len(linhas) >= 2, f"{onde}: cabeçalho sem corpo"


def test_as_cores_dizem_sempre_a_mesma_coisa(sector: Sector):
    """Três cores, e cada uma com um significado fixo.

    Doze widgets já são muita informação. Dar a cada um a sua cor
    transforma a página num mostruário em vez de um argumento — por isso
    a paleta é curta, e por isso não se inventam cores por página.
    """
    permitidas = {
        (AMBAR["fundo"], AMBAR["texto"]),
        (AZUL["fundo"], AZUL["texto"]),
        (VERDE["fundo"], VERDE["texto"]),
    }
    for p, w in _blocos_de_texto(sector):
        dados = w.dados([_LinhaEspia(1)])
        par = (dados["backgroundColor"], dados["textColor"])
        assert par in permitidas, (
            f"{sector.chave} / {p.nome} / {w.titulo}: cor fora da paleta — {par}"
        )


def test_as_tres_cores_leem_se_nos_dois_temas(sector: Sector):
    """Fundo e texto são os dois explícitos, de propósito.

    O amarelo da marca como texto dá 1,78:1 num fundo claro e 9,7:1 num
    escuro — foi preciso rever um ecrã inteiro por causa disso. Aqui o
    bloco traz o seu próprio fundo, por isso o contraste é o mesmo nos
    dois temas e não depende do que estiver por baixo.
    """
    del sector  # a paleta é global; o fixture só evita repetir o import
    for cor in (AMBAR, AZUL, VERDE):
        assert cor["fundo"].startswith("#") and len(cor["fundo"]) == 7
        assert cor["texto"].startswith("#") and len(cor["texto"]) == 7
        # O texto tem de ser MUITO mais escuro do que o fundo. A soma dos
        # canais serve de aproximação grosseira e suficiente: o que isto
        # impede é a troca distraída dos dois.
        soma = lambda h: sum(int(h[i : i + 2], 16) for i in (1, 3, 5))  # noqa: E731
        assert soma(cor["fundo"]) - soma(cor["texto"]) > 300, cor


# ── o ajudante dos parágrafos ───────────────────────────────────────


def test_paragrafos_separa_com_uma_linha_em_branco():
    assert paragrafos("um", "dois") == "um\n\ndois"


def test_paragrafos_deixa_de_fora_o_que_esta_vazio():
    """Para um `corpo` poder omitir uma frase sem deixar o espaço dela.

    Sem isto, um parágrafo condicional que não se aplica abria um buraco
    no meio do cartão — e isso não se vê a ler o código.
    """
    assert paragrafos("um", "", "dois") == "um\n\ndois"
    assert paragrafos("um", "   ", "dois") == "um\n\ndois"
    assert paragrafos() == ""


# ── a grelha ────────────────────────────────────────────────────────


def test_as_filas_de_texto_nao_colidem_com_as_de_corpo():
    """O primeiro erro deste desenho, e o que o apanhou.

    A fila dos textos fica ENTRE a primeira e a segunda filas de corpo.
    Calcular o topo da fila `n` com `n * (altura + espaço)` punha a
    segunda por cima dos textos — e o
    `test_nenhum_widget_fica_por_cima_de_outro` chumbou.
    """
    from scripts.demo_sectorial.pecas import _ranhura

    texto_pos, texto_tam = _ranhura("terco1a")
    fila1_pos, fila1_tam = _ranhura("esq1")
    fila2_pos, _ = _ranhura("esq2")

    # O texto fica depois da primeira fila…
    assert texto_pos["y"] >= fila1_pos["y"] + fila1_tam["height"]
    # …e a segunda fila depois do texto.
    assert fila2_pos["y"] >= texto_pos["y"] + texto_tam["height"]


def test_uma_quarta_fila_sai_abaixo_da_terceira():
    """Sem limite superior, de propósito.

    A primeira versão parava nas três filas, e a segunda página dos
    transportes — que já gastava `larga1` e `larga2` — ficou sem sítio
    para os dois gráficos novos. Uma grelha que obriga a reescrever a
    página quando se lhe acrescenta uma peça não é uma grelha.
    """
    from scripts.demo_sectorial.pecas import _ranhura

    _, tam3 = _ranhura("larga3")
    pos3, _ = _ranhura("larga3")
    pos4, _ = _ranhura("larga4")
    assert pos4["y"] >= pos3["y"] + tam3["height"]


def test_uma_ranhura_desconhecida_levanta():
    """Dois widgets sem posição ficariam um por cima do outro.

    E a página pareceria ter um widget a menos, sem erro nenhum — que é
    o modo de falhar mais difícil de notar numa reunião.
    """
    from scripts.demo_sectorial.pecas import _ranhura

    with pytest.raises(ValueError):
        _ranhura("meio3")
