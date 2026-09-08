"""QA — as notificacoes antigas nao podem ficar em ingles para sempre.

O Lucas abriu as notificacoes na app, em portugues, e leu:

    «Vendas do dia found 1 new insight»                 — 22 de Agosto

O mecanismo esta certo: o worker grava uma chave e a app monta a frase
na lingua de quem le. Mas as linhas gravadas ANTES dessa correccao so
tem o texto ingles, e a app faz o que deve — mostra o que la esta.

Ficam em ingles enquanto existirem. Ninguem as converteu.
"""

from __future__ import annotations

import importlib.util
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
MIGRACAO = (
    RAIZ / "migrations" / "versions" / "notificacoes_antigas_em_ingles_20260908.py"
)


def _modulo():
    spec = importlib.util.spec_from_file_location("migracao_notificacoes", MIGRACAO)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_migracao_existe():
    assert MIGRACAO.exists(), (
        "sem ela, todas as notificacoes escritas antes da correccao ficam em "
        "ingles para sempre"
    )


def test_o_padrao_apanha_o_singular_e_o_plural():
    p = _modulo()._PADRAO

    um = p.match("Vendas do dia found 1 new insight")
    assert um and um.group("agente") == "Vendas do dia" and um.group("conta") == "1"

    varios = p.match("Receita faturada found 3 new insights")
    assert varios and varios.group("conta") == "3"


def test_o_padrao_aguenta_um_nome_com_a_palavra_found():
    """O nome do agente e livre. Ancorar no inicio partia estes.

    Por isso a expressao ancora no FIM: o sufixo e que e fixo, e o que
    sobra a esquerda e o nome — por mais estranho que seja.
    """
    m = _modulo()._PADRAO.match("Agent found found 2 new insights")
    assert m and m.group("agente") == "Agent found"


def test_o_que_nao_bate_certo_fica_como_esta():
    """Uma notificacao em ingles e melhor do que uma com o nome errado."""
    p = _modulo()._PADRAO
    for texto in (
        "qualquer outra coisa",
        "found 2 new insights",  # sem nome de agente
        "Vendas found new insights",  # sem numero
        "",
    ):
        assert p.match(texto) is None, f"{texto!r} nao devia bater certo"


def test_a_migracao_nao_apaga_o_texto_ingles():
    """O `title` e a rede de seguranca para clientes antigos.

    Apaga-lo trocava uma notificacao em ingles por um ecra vazio, que e
    pior.
    """
    fonte = MIGRACAO.read_text(encoding="utf-8")
    assert "SET title_key" in fonte
    assert "title = " not in fonte.split("def downgrade")[0].replace(
        "title_key = ", ""
    ).replace("title_params = ", ""), "a migracao mexe no `title`, e nao devia"


def test_so_toca_em_linhas_sem_chave():
    """As notificacoes novas ja tem chave. Reescreve-las seria arriscar
    trocar valores certos por valores adivinhados de um texto."""
    fonte = MIGRACAO.read_text(encoding="utf-8")
    assert "title_key IS NULL" in fonte


def test_o_downgrade_nao_apaga_chaves():
    """Nao se distingue uma linha convertida de uma nascida com chave.

    Um downgrade que apagasse tudo deixava notificacoes novas sem forma
    de serem traduzidas — estragava mais do que desfazia.
    """
    fonte = MIGRACAO.read_text(encoding="utf-8")
    corpo = fonte.split("def downgrade")[1]
    assert "UPDATE" not in corpo.upper(), "o downgrade escreve na base"
