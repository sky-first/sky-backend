"""A língua da resposta: «segue a minha pergunta» tem de querer dizer isso.

> *"Responde em inglês num telemóvel em português."* — Lucas, item 7.1

**O que estava a acontecer.** O telemóvel tem duas definições separadas, e de
propósito: a língua **da app** e a língua em que **a Sky responde**. A segunda
tem um modo automático — «segue a sua pergunta» — que era enviado ao servidor
**por omissão**: não se mandava campo nenhum.

Só que o servidor lê a ausência do campo como *«este cliente é antigo e não
sabe disto»*, e cai na preferência guardada::

    if message_data.locale is None:
        message_data.locale = prefs.get("language", "pt")

O silêncio queria dizer duas coisas ao mesmo tempo. Quem tinha a app em
inglês, escolhia «segue a minha pergunta» e escrevia em português, recebia
**inglês** — e tinha escolhido explicitamente o contrário.

**A correcção** é dizer `auto` por palavras. A ausência continua a valer o que
sempre valeu (cliente antigo → preferência guardada), e a escolha passa a ter
como se exprimir.
"""

import inspect

import pytest

from src.api.v1 import ai as rotas
from src.schemas.ai import AIQueryRequest


def test_auto_sobrevive_ao_esquema():
    """Se o validador o normalizasse para `pt`, a escolha morria à entrada."""
    assert AIQueryRequest(question="x", locale="auto").locale == "auto"
    assert AIQueryRequest(question="x", locale="AUTO").locale == "auto"
    assert AIQueryRequest(question="x", locale=" auto ").locale == "auto"


@pytest.mark.parametrize("dito,esperado", [("pt", "pt"), ("en", "en"), ("pt-PT", "pt")])
def test_uma_lingua_escolhida_continua_a_valer(dito, esperado):
    """O `auto` não pode ter estragado o caminho normal."""
    assert AIQueryRequest(question="x", locale=dito).locale == esperado


def test_nao_dizer_nada_continua_a_ser_nao_dizer_nada():
    """**A distinção que faltava.**

    Ausência = cliente antigo, e aí a preferência guardada vale. É o
    comportamento de sempre, e não se toca nele.
    """
    assert AIQueryRequest(question="x").locale is None


def test_o_servidor_converte_auto_em_deixa_o_motor_detectar():
    """Passar a palavra `auto` ao motor era pedir-lhe resposta em «auto».

    A conversão é **depois** da queda para as preferências: se fosse antes, o
    `auto` virava `None` e a linha seguinte enchia-o com a preferência
    guardada — exactamente o defeito que se está a corrigir.
    """
    fonte = inspect.getsource(rotas)
    assert fonte.count('locale", None) == "auto"') >= 2, (
        "algum caminho de pergunta deixou de honrar o «segue a minha pergunta»"
    )
    # A ordem importa: a conversão vem depois do `prefs.get`.
    i_prefs = fonte.index('prefs.get("language"')
    i_auto = fonte.index('locale", None) == "auto"')
    assert i_auto > i_prefs


def test_os_tres_caminhos_de_pergunta_estao_cobertos():
    """`/ai/query`, `/ai/chat` e `/ai/chat/stream`.

    O telemóvel usa o streaming; a web usa os outros. Corrigir um só deixava
    o mesmo defeito no ecrã ao lado.
    """
    fonte = inspect.getsource(rotas)
    assert fonte.count('locale", None) == "auto"') == 3
