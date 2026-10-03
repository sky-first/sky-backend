# -*- coding: utf-8 -*-
"""As falhas da conversa falam a língua de quem pergunta.

── O que o Lucas viu ───────────────────────────────────────────────

Numa plataforma configurada em português, a Sky respondeu:

    The AI service rejected the request. Please retry or open a ticket.

Duas coisas erradas na mesma linha. Está em inglês, e manda abrir um
pedido de apoio que não existe — não há botão nenhum nesse ecrã para o
abrir.

── Porque é que nenhum guarda de i18n viu ──────────────────────────

Os guardas de i18n vivem no frontend e varrem `.tsx` e os dicionários.
Esta frase é do **backend**, numa cadeia de `elif` que classifica
excepções do `httpx`. Sete ramos, e só o do `400` pedia a frase ao
`get_message`; os outros seis estavam cravados.

Um deles — o `else` final — era o que apanhava o `404`, que é o código
que o `sky-ai` devolve quando a ligação não tem metadados. Ou seja: a
causa mais provável caía no ramo com a pior mensagem.

── O que este teste fixa ───────────────────────────────────────────

O comportamento: a mesma falha, em três línguas, dá três frases
diferentes; e nenhuma delas promete um botão que não existe.
"""

from __future__ import annotations

import inspect
import re

import pytest

from src.core.locale import get_message

CHAVES = [
    "chat_error_generic",
    "chat_error_timeout",
    "chat_error_rate_limited",
    "chat_error_unavailable",
    "chat_error_network",
    "chat_error_no_metadata",
    "couldnt_understand",
]
IDIOMAS = ["pt", "en", "es"]


@pytest.mark.parametrize("chave", CHAVES)
def test_existe_nas_tres_linguas(chave: str):
    for idioma in IDIOMAS:
        frase = get_message(chave, idioma)
        assert frase and frase != chave, f"{chave}/{idioma} não está traduzida"


@pytest.mark.parametrize("chave", CHAVES)
def test_o_portugues_nao_e_o_ingles_copiado(chave: str):
    # O contrapeso. Preencher o catálogo com o texto inglês passava o
    # teste acima e deixava o ecrã exactamente como estava.
    assert get_message(chave, "pt") != get_message(chave, "en")
    assert get_message(chave, "es") != get_message(chave, "en")


@pytest.mark.parametrize("chave", CHAVES)
def test_nenhuma_promete_um_botao_que_nao_existe(chave: str):
    # A frase antiga dizia «open a ticket» e não havia por onde.
    # Prometer uma acção que o ecrã não dá é pior do que não dizer nada:
    # quem lê vai procurar o botão e conclui que a culpa é dele.
    proibidas = ("ticket", "abrir um pedido", "abra un ticket", "support")
    for idioma in IDIOMAS:
        frase = get_message(chave, idioma).lower()
        achadas = [p for p in proibidas if p in frase]
        assert not achadas, f"{chave}/{idioma} promete {achadas}"


@pytest.mark.parametrize("chave", CHAVES)
def test_o_portugues_e_de_portugal_e_trata_por_voce(chave: str):
    # As duas regras da casa, nas frases novas como nas antigas.
    pt = get_message(chave, "pt")
    assert not re.search(r"\b(você|tu)\b.*\bteus?\b", pt, re.IGNORECASE)
    for brasileirismo in ("tela", "arquivo", "usuário", "conexão"):
        assert brasileirismo not in pt.lower(), f"{chave}: «{brasileirismo}»"


def test_o_classificador_nao_tem_frases_cravadas():
    """Nenhum ramo escreve a frase à mão — todos pedem ao catálogo.

    Olha para a função que classifica a excepção, e não para o ficheiro
    todo: o `ai_service` tem texto inglês legítimo noutros sítios
    (prompts, registos), e um guarda que falha com esses é um guarda que
    alguém desliga na semana seguinte.
    """
    from src.services import ai_service

    fonte = inspect.getsource(ai_service)
    inicio = fonte.index('error_key = "chat.server"')
    bloco = fonte[inicio : inicio + 2200]
    # Fora os comentários, que citam a frase antiga para a explicar.
    sem_comentarios = "\n".join(
        linha for linha in bloco.splitlines() if not linha.strip().startswith("#")
    )
    atribuicoes = re.findall(r"friendly\s*=\s*(.+)", sem_comentarios)
    assert atribuicoes, "o bloco mudou de forma — este guarda deixou de verificar nada"
    cravadas = [a for a in atribuicoes if "get_message" not in a]
    assert not cravadas, f"frases cravadas: {cravadas}"


def test_o_404_tem_ramo_proprio():
    """Um 404 quer dizer «sem metadados», não «pedido recusado».

    Caía no `else` genérico, e a mensagem mandava procurar um defeito no
    serviço de IA — que estava bom. Custou-nos uma demonstração.
    """
    from src.services import ai_service

    fonte = inspect.getsource(ai_service)
    assert "code == 404" in fonte
    assert "chat_error_no_metadata" in fonte
