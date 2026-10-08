# -*- coding: utf-8 -*-
"""O tom e o estilo escolhidos nas Definições morriam no chão.

── O defeito ───────────────────────────────────────────────────────

O `/chat` não-streaming manda `ai_tone` e `ai_style` ao motor desde
sempre. O `/chat/stream` **resolvia-os das preferências do utilizador** —
três linhas a ir buscá-los — e depois chamava um cliente que não tinha
parâmetro onde os pôr. Ficavam no objecto e nunca saíam.

Efeito: quem escolhesse «directo» ou «formal» nas Definições via a
escolha respeitada no `/chat` e ignorada no chat a sério, que é
streaming. O `sky-ai` sempre os aceitou neste endpoint
(`QueryRequest.ai_tone`, usado em `_build_user_preferences_block`) —
faltava só mandá-los.

É o mesmo padrão do #713 na voz: o caminho novo nasceu com menos campos
do que o antigo e ninguém comparou os dois. Daí o teste de PARIDADE em
baixo, que é o que impede a terceira vez.

── O que este teste NÃO faz ────────────────────────────────────────

Não verifica que a resposta sai com o tom certo — isso é do formatador
do `sky-ai` e mede-se a ler. Verifica que a escolha da pessoa CHEGA lá.
Um teste que confirmasse a formatação estaria a fixar o prompt de outro
serviço.
"""
from __future__ import annotations

import inspect

import pytest

from src.ai.http_client import AIServiceHTTPClient


def _assinatura(fn) -> set[str]:
    return set(inspect.signature(fn).parameters)


class TestOClienteTemOndeOsPor:
    def test_o_streaming_aceita_tom_e_estilo(self):
        p = _assinatura(AIServiceHTTPClient.stream_query_connection)
        em_falta = {"ai_tone", "ai_style"} - p
        assert not em_falta, (
            f"o cliente de streaming não aceita {em_falta} — a rota "
            "resolve-os das preferências e eles morrem aqui"
        )

    @pytest.mark.parametrize("campo", ["ai_tone", "ai_style"])
    def test_e_mete_os_na_carga(self, campo):
        fonte = inspect.getsource(AIServiceHTTPClient.stream_query_connection)
        assert f'payload["{campo}"] = {campo}' in fonte, (
            f"{campo} é aceite e não vai na carga — pior do que não o "
            "aceitar, porque parece resolvido"
        )


class TestAParidadeEntreOsDoisCaminhos:
    """O contrapeso: o que o `/chat` manda, o `/chat/stream` manda.

    Esta lista é a fronteira. Quando um dos dois ganhar um campo novo e
    o outro não, isto falha e obriga a decidir em vez de divergir em
    silêncio — que foi exactamente como se chegou aqui, duas vezes.
    """

    #: Campos de PREFERÊNCIA do utilizador que os dois têm de mandar.
    PARIDADE = ("ai_tone", "ai_style", "locale")

    def test_os_dois_clientes_aceitam_os_mesmos(self):
        streaming = _assinatura(AIServiceHTTPClient.stream_query_connection)
        normal = _assinatura(AIServiceHTTPClient.query_connection)
        for campo in self.PARIDADE:
            assert campo in normal, f"/chat deixou de aceitar {campo}"
            assert campo in streaming, f"/chat/stream não aceita {campo}"

    def test_a_rota_de_streaming_passa_os_que_resolve(self):
        """O detalhe que dói: a rota já os ia buscar e deitava fora.

        As três linhas que lêem `prefs.get("ai_tone")` existem desde que
        a rota nasceu. Resolver uma preferência e não a usar é pior do
        que não a resolver — deixa a leitura no sítio certo para quem
        procurar o defeito não o encontrar.
        """
        from src.api.v1 import ai as rota

        fonte = inspect.getsource(rota)
        for campo in ("ai_tone", "ai_style"):
            assert f'prefs.get("{campo}")' in fonte, (
                f"a rota deixou de resolver {campo} das preferências"
            )
            assert f"{campo}=message_data.{campo}" in fonte, (
                f"a rota resolve {campo} e não o passa adiante"
            )


class TestAVozLevaOTomMasNaoOEstilo:
    """Uma diferença de propósito, e escrita para não ser "corrigida".

    O estilo é sobre a FORMA do texto: `step-by-step` manda numerar
    «1., 2., 3.» e `detailed` pede cabeçalho e ressalvas. Ditos em voz
    alta ficam péssimos. O tom («casual», «profissional») é sobre como a
    pessoa quer ser tratada, e isso vale falado como escrito.
    """

    def test_a_voz_manda_o_tom(self):
        from src.api.v1 import voice

        fonte = inspect.getsource(voice._voice_answer)  # noqa: SLF001
        assert "ai_tone=" in fonte, "a voz deixou de respeitar o tom escolhido"

    def test_e_nao_manda_o_estilo(self):
        from src.api.v1 import voice

        fonte = inspect.getsource(voice._voice_answer)  # noqa: SLF001
        assert "ai_style=" not in fonte, (
            "alguém acrescentou o estilo à voz por simetria — ler «um, "
            "dois, três» em voz alta é pior do que não respeitar a "
            "escolha. Se for para mudar, mude-se este teste primeiro"
        )
