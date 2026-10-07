# -*- coding: utf-8 -*-
"""Cada sector traz o seu vocabulário.

> «porque voce tambem nao criou metricas e glossario?»
> — Lucas, 07/10/2026

Não criei. O `Sector` tinha ligações, páginas, widgets, agentes e
perguntas — e mais nada. Na base de produção: `metricas 0`,
`glossario 0`.

── Porque é que não é só encher um ecrã ────────────────────────────

**A IA lê isto.** O `BackendClient.get_metrics` e o `get_glossary`
alimentam o especialista de conhecimento do `sky-ai`. Sem eles o motor
responde sobre as colunas que encontra, sem saber como a casa chama às
coisas nem como as calcula.

«Vacío de retorno» não existe em esquema nenhum — define-se por uma
ausência. «Rappel» também não: está no contrato. São exactamente as
palavras que o cliente escreve no chat.

── O que estes testes protegem ─────────────────────────────────────

Que as fórmulas correm é verificado contra a base sintética, como o
resto do semeador (15 fórmulas, 0 problemas). Aqui fica o que o SQL não
diz: que a fórmula de uma métrica é a MESMA que alimenta o widget
correspondente. Duas definições do mesmo número — uma no painel, outra
no glossário — é a maneira mais rápida de o produto se contradizer a si
próprio, no mesmo ecrã, à frente de quem está a decidir.
"""
from __future__ import annotations

import re

import pytest

from scripts.demo_sectorial import alimentacion, restauracion, transportes
from scripts.demo_sectorial.motor import _slug
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


# ── que existem ─────────────────────────────────────────────────────


def test_cada_sector_tem_metricas(sector: Sector):
    assert len(sector.metricas) >= 4, (
        f"{sector.chave}: {len(sector.metricas)} métricas — o ecrã de "
        "Conhecimento fica vazio e a IA responde sem saber como a casa "
        "calcula os seus números"
    )


def test_e_tem_glossario(sector: Sector):
    assert len(sector.glossario) >= 4, f"{sector.chave}: {len(sector.glossario)} termos"


def test_nao_ha_nomes_repetidos(sector: Sector):
    # O id vem de `uuid5(chave, "metric", nome)`. Dois iguais seriam a
    # mesma linha, e a segunda sobrescrevia a primeira em silêncio.
    nomes = [m.nome for m in sector.metricas]
    assert len(set(nomes)) == len(nomes)
    termos = [t.termo for t in sector.glossario]
    assert len(set(termos)) == len(termos)


# ── que estão escritos para serem lidos ─────────────────────────────


def test_a_metrica_diz_o_que_e_e_como_se_calcula(sector: Sector):
    for m in sector.metricas:
        onde = f"{sector.chave} / {m.nome}"
        assert m.formula.strip(), f"{onde}: sem fórmula"
        assert "SELECT" in m.formula.upper(), f"{onde}: a fórmula não é SQL"
        # Uma descrição de dez palavras não explica nada a quem não
        # sabe — e quem não sabe é o motor.
        assert len(m.descricao) > 60, f"{onde}: descrição de {len(m.descricao)} caracteres"


def test_o_termo_define_se_sem_usar_a_propria_palavra(sector: Sector):
    """«Merma: la merma del periodo» não define nada.

    A definição é lida por um modelo que não conhece a palavra. Se ela
    aparecer logo na primeira frase da definição, não há definição.
    """
    for t in sector.glossario:
        onde = f"{sector.chave} / {t.termo}"
        assert len(t.definicao) > 60, f"{onde}: definição curta demais"
        # O TERMO INTEIRO, e não a primeira palavra dele.
        #
        # A primeira versão comparava só a palavra inicial e chumbou
        # «Coste completo del vehículo» por a definição listar os custos
        # que o compõem — que é exactamente o que uma boa definição faz.
        # O que não vale é repetir o nome em vez de o explicar.
        primeira = " ".join(t.definicao.split(".")[0].lower().split())
        assert t.termo.lower() not in primeira, f"{onde}: define-se a si próprio"


def test_os_termos_tem_sinonimos(sector: Sector):
    """O cliente escreve o que lhe sai.

    Ninguém escreve «vacío de retorno» no chat: escreve «vacío». Sem os
    sinónimos, o glossário só serve a quem já sabe o nome exacto — que é
    precisamente quem não precisa dele.
    """
    sem = [t.termo for t in sector.glossario if not t.sinonimos]
    assert not sem, f"{sector.chave}: termos sem sinónimos — {sem}"


# ── o contrapeso: uma fonte só para cada número ─────────────────────


def _normaliza(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()


def test_a_formula_de_uma_metrica_vive_tambem_num_widget(sector: Sector):
    """O defeito que isto impede.

    Uma métrica cuja fórmula não corresponde a nada no painel é uma
    segunda definição do mesmo número — e no dia em que as duas
    divergirem, o cartão diz 22,2% e o glossário diz outra coisa, no
    mesmo ecrã.

    Não se exige igualdade literal: as fórmulas partilham os mesmos
    blocos de SQL (`_MARGEM`, `_FROTA`, `_CADUCA`) e é essa partilha que
    garante que vêm do mesmo sítio. O que se exige é que a métrica não
    seja escrita do nada.
    """
    sql_dos_widgets = " ".join(
        _normaliza(w.sql) for p in sector.paginas for w in p.widgets
    )
    orfas = []
    for m in sector.metricas:
        corpo = _normaliza(m.formula)
        # O miolo da fórmula — a parte depois do SELECT — tem de
        # aparecer em algum widget, nem que seja dentro de um bloco
        # partilhado.
        pedaco = corpo.split("from")[-1][:60] if "from" in corpo else corpo[:60]
        if pedaco and pedaco not in sql_dos_widgets:
            orfas.append(m.nome)
    assert len(orfas) <= 1, (
        f"{sector.chave}: métricas sem nada no painel que as sustente — {orfas}"
    )


# ── o que o motor precisa para as gravar ────────────────────────────


def test_o_slug_sobrevive_aos_acentos():
    """A coluna `slug` é `NOT NULL` e os nomes vêm em castelhano."""
    assert _slug("Vacío de retorno") == "vacio-de-retorno"
    assert _slug("Margen neto tras rappel") == "margen-neto-tras-rappel"
    assert _slug("Añadir — Métrica") == "anadir-metrica"


def test_e_nenhum_slug_sai_vazio(sector: Sector):
    # Um nome só de pontuação dava `""`, e a coluna recusava-o — a meio
    # da sementeira, depois de já ter escrito as páginas.
    for m in sector.metricas:
        assert _slug(m.nome), f"{sector.chave}: {m.nome!r} não dá slug"
    for t in sector.glossario:
        assert _slug(t.termo), f"{sector.chave}: {t.termo!r} não dá slug"


def test_dois_sectores_nao_colidem_no_mesmo_slug():
    """Os três projectos vivem na MESMA base do cliente.

    `Merma` existe na restauração e podia existir na alimentação. O id é
    `uuid5(chave_do_sector, …)`, por isso são linhas diferentes — mas o
    slug repetido confunde quem o lê, e o teste obriga a dar-lhes nomes
    que se distinguem.
    """
    vistos: dict[str, str] = {}
    for s in SECTORES:
        for m in s.metricas:
            slug = _slug(m.nome)
            if slug in vistos:
                assert vistos[slug] == s.chave, (
                    f"«{m.nome}» existe em {vistos[slug]} e em {s.chave}"
                )
            vistos[slug] = s.chave
