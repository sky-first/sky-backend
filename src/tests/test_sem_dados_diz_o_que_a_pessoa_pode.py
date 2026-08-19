"""A resposta de "sem dados" tem de dizer o que a pessoa **pode** fazer.

Encontrado a perguntar ao chat em produção com a conta `teste.member@`:

    "This space has no data connections yet. Connect a data source from the
     toolbar (Sources → Connect) so I can answer questions grounded in your
     data."

Duas coisas erradas na mesma frase:

  1. está em inglês, num produto que fala português ao cliente;
  2. manda um member ligar uma fonte de dados — coisa que a plataforma lhe
     recusa, porque cunhar ligações é decisão do cliente. A única instrução
     no ecrã é o que ele não pode fazer.

O mesmo defeito estava no frontend e foi corrigido nesse dia. O backend tinha
a sua própria cópia, escrita à mão, fora do catálogo de mensagens — que é
precisamente porque escapou.
"""

from __future__ import annotations

from pathlib import Path

from src.core.locale import get_message

FONTE = Path("src/services/ai_service.py").read_text(encoding="utf-8")


def test_a_frase_saiu_do_codigo_para_o_catalogo():
    assert "This space has no data connections yet" not in FONTE, (
        "a frase voltou a ser escrita à mão — fica fora do catálogo e escapa "
        "a qualquer verificação de língua"
    )
    assert 'get_message(chave, lingua)' in FONTE


def test_quem_pode_ligar_dados_e_convidado_a_liga_los():
    frase = get_message("space_has_no_data_can_connect", "pt")
    assert "Ligue uma fonte" in frase


def test_quem_nao_pode_e_encaminhado_para_o_pedido():
    frase = get_message("space_has_no_data_ask_access", "pt")
    assert "Peça acesso" in frase
    # Tem de apontar um caminho concreto, senão é só um "não".
    assert "Pedir dados" in frase


def test_as_duas_frases_sao_diferentes():
    """Se alguém as unificar, um dos dois lados volta ao beco sem saída."""
    assert get_message("space_has_no_data_can_connect", "pt") != get_message(
        "space_has_no_data_ask_access", "pt"
    )


def test_existem_nas_duas_linguas():
    for chave in ("space_has_no_data_can_connect", "space_has_no_data_ask_access"):
        pt = get_message(chave, "pt")
        en = get_message(chave, "en")
        assert pt and en and pt != en, chave


def test_a_escolha_depende_do_papel_e_nao_do_acaso():
    """A decisão tem de ser `is_tenant_admin`, não uma comparação à mão.

    Foi uma tupla escrita à mão que deixou um admin promover-se a fundador
    esta semana; não se repete o padrão aqui.
    """
    assert "is_tenant_admin(quem)" in FONTE
