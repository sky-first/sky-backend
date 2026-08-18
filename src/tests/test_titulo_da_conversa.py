"""A conversa ganha nome na primeira coisa que lá se escreve.

Nascia sem título e ficava assim para sempre. A lista de conversas era uma
coluna de "Sem título" e o cabeçalho dizia o mesmo — quem tem cinco conversas
não distingue nenhuma.

O nome sai da primeira mensagem, como no ChatGPT e no Claude, e é feito no
servidor para a web e a app terem o mesmo comportamento sem esperar por um APK.
"""
from __future__ import annotations

from src.services.message_service import _MAX_TITULO, _titulo_a_partir_de


def test_uma_pergunta_curta_fica_inteira():
    assert _titulo_a_partir_de("Como fechou Julho?") == "Como fechou Julho?"


def test_a_primeira_frase_manda_quando_cabe():
    titulo = _titulo_a_partir_de(
        "Como fechou Julho? Preciso disto para a reunião de amanhã com o banco."
    )
    assert titulo == "Como fechou Julho?"


def test_texto_longo_e_cortado_na_palavra():
    texto = (
        "Preciso de perceber porque é que a margem do trimestre passado ficou "
        "abaixo do orçamento em todas as regiões menos o Sul"
    )
    titulo = _titulo_a_partir_de(texto)
    assert len(titulo) <= _MAX_TITULO + 1  # +1 pelas reticências
    assert titulo.endswith("…")
    # Cortar a meio de uma palavra faz a lista tropeçar na leitura.
    assert not titulo[:-1].endswith(" ")
    assert texto.startswith(titulo[:-1].rstrip())


def test_quebras_de_linha_e_espacos_a_mais_desaparecem():
    assert _titulo_a_partir_de("  Como   fechou\n\nJulho  ") == "Como fechou Julho"


def test_texto_vazio_nao_inventa_titulo():
    assert _titulo_a_partir_de("") == ""
    assert _titulo_a_partir_de("   \n  ") == ""


def test_nao_termina_em_pontuacao_solta():
    titulo = _titulo_a_partir_de("a" * 40 + " , " + "b" * 40)
    assert not titulo.rstrip("…").endswith(",")
