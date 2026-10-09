# -*- coding: utf-8 -*-
"""A ponte entre a sessão falada e o protocolo que a app já fala.

── O que está em jogo ──────────────────────────────────────────────

**O protocolo com a app não muda.** Nem um campo. A app e a web não
sabem que o motor por baixo é outro — e é essa a condição para se poder
voltar atrás numa variável de ambiente, num produto que é demonstrado a
clientes.

Sem OTA na app (ver `sky-mobile`), um tipo de mensagem novo obrigaria a
uma build nativa para qualquer coisa acontecer. Isso é semanas, e
transformava «virar uma bandeira» em «lançar uma versão». Daí a
tradução: o motor novo fala para dentro do vocabulário antigo.

── E a ferramenta ──────────────────────────────────────────────────

A ferramenta que o modelo chama é o `_voice_answer` do `voice.py`,
injectado. Não é preguiça: ele carrega **todo** o trabalho de paridade
com o chat escrito — as ligações todas do projecto, o glossário, o tom,
a língua. Foi o que o #713 corrigiu, e era exactamente a razão pela qual
a voz «não encontrava dados». Reescrevê-la para o Sonic era herdar o
defeito outra vez.
"""
from __future__ import annotations

from typing import Any, List

import pytest

from src.services import voz_fala_a_fala as falada
from src.services import voz_ponte_sonic as ponte


class _Ctx:
    slug = "cliente-de-teste"


# ── A tradução ──────────────────────────────────────────────────────


class TestOProtocoloNaoMuda:
    """Cada `type` que sai daqui tem de ser um que a app já trata."""

    #: O vocabulário que a app conhece hoje. Ver
    #: `sky-mobile/apps/mobile/src/voice/voiceWs.ts`.
    CONHECIDOS = {
        "state",
        "partial_transcript",
        "sky_text",
        "tts_audio",
        "discard_audio",
        "final",
        "error",
    }

    #: E os valores de `state` que ela conhece.
    ESTADOS = {"connecting", "user_speaking", "thinking", "speaking", "ended"}

    @pytest.mark.parametrize(
        "evento",
        [
            falada.Ouvido(texto="olá"),
            falada.Dito(texto="olá"),
            falada.Audio(pcm=b"\x01\x02"),
            falada.FalaAcabou(),
            falada.APensar(pergunta="quantas rutas?"),
            falada.Interrompido(),
            falada.Falhou(porque="x"),
        ],
    )
    def test_nenhum_evento_inventa_vocabulario(self, evento):
        for m in ponte.para_o_protocolo(evento):
            assert m["type"] in self.CONHECIDOS, (
                f"`{m['type']}` não existe na app — e sem OTA, ensiná-lo " "custa uma build nativa"
            )
            if m["type"] == "state":
                assert m["value"] in self.ESTADOS, f"estado novo: {m['value']}"


class TestCadaEventoNoSeuSitio:
    def test_a_transcricao_vai_como_transcricao(self):
        """E `final: True`: o modelo não manda parciais da fala da pessoa.

        Marcá-la como parcial fazia o ditado — que usa o mesmo campo —
        tratar cada frase como uma reescrita da anterior, e perder tudo o
        que foi dito antes da primeira pausa.
        """
        [m] = ponte.para_o_protocolo(falada.Ouvido(texto="quantas rutas?"))
        assert m == {
            "type": "partial_transcript",
            "text": "quantas rutas?",
            "final": True,
        }

    def test_a_legenda_da_sky_vai_como_sky_text(self):
        ms = ponte.para_o_protocolo(falada.Dito(texto="São duas."))
        assert {"type": "sky_text", "text": "São duas."} in ms

    def test_e_diz_que_ela_COMECOU_a_falar(self):
        """O buraco que quase ficou.

        Sem isto a app continuava a mostrar «a Sky está a pensar»
        enquanto ela já falava. Vai com a legenda e não com o áudio
        porque o `textOutput` chega imediatamente antes do primeiro
        pedaço de som — medido — e pendurá-lo no áudio obrigava a mandar
        o estado centenas de vezes por turno.
        """
        ms = ponte.para_o_protocolo(falada.Dito(texto="São duas."))
        assert ms[0] == {"type": "state", "value": "speaking"}, (
            "o estado tem de vir ANTES da legenda: primeiro sai-se do "
            "«a pensar», depois mostra-se o que ela diz"
        )

    def test_e_o_audio_NAO_repete_o_estado(self):
        """Centenas de pedaços por turno: um estado em cada era ruído."""
        for m in ponte.para_o_protocolo(falada.Audio(pcm=b"\x01")):
            assert m["type"] != "state"

    def test_o_audio_sai_marcado_e_nao_formatado(self):
        """Os bytes não entram num JSON.

        Pô-los em base64 aqui era inflá-los por nada: o socket já leva
        binário, e é assim que a app os espera.
        """
        [m] = ponte.para_o_protocolo(falada.Audio(pcm=b"\x01\x02\x03"))
        assert ponte.e_audio(m)
        assert m["pcm"] == b"\x01\x02\x03"

    def test_e_nada_mais_e_audio(self):
        for ev in (falada.Dito(texto="x"), falada.FalaAcabou()):
            for m in ponte.para_o_protocolo(ev):
                assert not ponte.e_audio(m)

    def test_o_fim_da_fala_para_de_mostrar_a_ouvir(self):
        [m] = ponte.para_o_protocolo(falada.FalaAcabou())
        assert m == {"type": "state", "value": "thinking"}

    def test_o_a_pensar_usa_um_estado_QUE_A_APP_JA_TRATA(self):
        """O recado do cliente depende disto, e um tipo novo não servia.

        **Medido:** o modelo cala-se enquanto a ferramenta corre e não há
        como o convencer a avisar. O «deixa-me ver» vem do cliente — mas
        só se ele souber quando, e só se o soubermos dizer com o
        vocabulário que ele já tem instalado.
        """
        [m] = ponte.para_o_protocolo(falada.APensar(pergunta="x"))
        assert m == {"type": "state", "value": "thinking"}


class TestAInterrupcaoManda_DUAS_coisas:
    """E as duas são precisas, por razões diferentes."""

    def test_descarta_e_devolve_o_microfone(self):
        ms = ponte.para_o_protocolo(falada.Interrompido())
        tipos = [m["type"] for m in ms]
        assert "discard_audio" in tipos, (
            "sem isto a Sky é cortada no servidor e continua a falar no "
            "auscultador — o áudio já enviado toca de qualquer maneira"
        )
        assert {"type": "state", "value": "user_speaking"} in ms, (
            "sem isto a app descarta o áudio e fica a achar que a Sky " "ainda está a falar"
        )

    def test_e_o_descarte_vem_PRIMEIRO(self):
        """A ordem importa: calar antes de dizer que o microfone é dela."""
        ms = ponte.para_o_protocolo(falada.Interrompido())
        assert ms[0]["type"] == "discard_audio"


class TestAAvaria:
    def test_vai_com_o_codigo_que_a_app_distingue(self):
        """`turn_failed` significa «esta pergunta falhou, continua a ouvir».

        Um erro SEM código desliga a sessão inteira — a app distingue-os
        pelo código, e já foi preciso corrigir isso uma vez.
        """
        [m] = ponte.para_o_protocolo(falada.Falhou(porque="ValidationException: x"))
        assert m["type"] == "error"
        assert m["code"] == "turn_failed"

    def test_e_NAO_manda_frase_nenhuma(self):
        """A frase escolhe-se na app, na língua de quem lê.

        A app faz `onError(e.message || e.code)` e só traduz quando a
        `message` vem vazia. Mandar uma frase atropela a tradução.

        Foi o que aconteceu: a minha primeira versão mandava «Não
        consegui responder a isso.» cravado em português, e apareceu
        **por cima de uma app em espanhol**. A cascata já fazia isto
        bem — eu li o comentário dela e não o segui.
        """
        [m] = ponte.para_o_protocolo(
            falada.Falhou(porque="ValidationException: Invalid input request")
        )
        assert "message" not in m, (
            f"mandou uma frase ({m.get('message')!r}) — a app vai "
            "mostrá-la tal e qual, na língua em que estiver escrita"
        )

    def test_e_a_razao_NAO_vai_para_o_ouvido(self):
        """Quem está do outro lado não quer ouvir o nome da excepção."""
        [m] = ponte.para_o_protocolo(
            falada.Falhou(porque="ValidationException: Invalid input request")
        )
        assert "ValidationException" not in str(m)
        assert "Invalid input" not in str(m)


# ── A ferramenta ────────────────────────────────────────────────────


def _ferramenta(responder) -> falada.Ferramenta:
    return ponte.ferramenta_do_cliente(
        responder,
        user=object(),
        page_id="pagina-1",
        ctx=_Ctx(),
        locale="pt",
        space_id="projeto-1",
    )


class TestAFerramentaChamaOMotorDeSempre:
    @pytest.mark.asyncio
    async def test_a_pergunta_e_o_contexto_chegam_ao_motor(self):
        vistos: List[Any] = []

        async def responder(user, page_id, texto, ctx, locale, space_id=None):
            vistos.append((texto, locale, space_id, getattr(ctx, "slug", None)))
            return "São duas rotas."

        assert await _ferramenta(responder)("quantas rutas?") == "São duas rotas."
        assert vistos == [("quantas rutas?", "pt", "projeto-1", "cliente-de-teste")]

    @pytest.mark.asyncio
    async def test_o_projeto_vai_a_serio(self):
        """O defeito que o #713 corrigiu não pode voltar por aqui.

        Perguntar pela voz dentro de um projeto SEM dados respondia com
        os dados de outro, porque o `space_id` ia fixo em `"default"`.
        """
        vistos: List[Any] = []

        async def responder(user, page_id, texto, ctx, locale, space_id=None):
            vistos.append(space_id)
            return "x"

        f = ponte.ferramenta_do_cliente(
            responder,
            user=object(),
            page_id=None,
            ctx=_Ctx(),
            locale="es",
            space_id=None,  # modo pessoal, que é legítimo
        )
        await f("algo")
        assert vistos == [None], "o modo pessoal não pode virar um projeto"


class TestAsTresRespostasChegamSEMPRE:
    """Nenhuma pode levantar excepção daqui para fora.

    Um `toolResult` que não chega deixa o modelo à espera — até aos 55 s
    — e a sessão morre com a pessoa à espera. **Só o modelo pode falar**,
    portanto tudo tem de lhe chegar em texto.
    """

    @pytest.mark.asyncio
    async def test_avariou_vira_texto(self):
        async def responder(*_a, **_k):
            return None  # FALHOU_A_RESPOSTA

        assert await _ferramenta(responder)("x") == ponte.AVARIOU

    @pytest.mark.asyncio
    async def test_sem_dados_vira_outro_texto(self):
        """«Não encontrei» e «avariou» são coisas diferentes para quem ouve.

        Juntá-las foi metade do defeito que o #713 corrigiu: a voz dizia
        «não encontrei dados» quando o que se passava era que o motor não
        recebia metade do contexto.
        """

        async def responder(*_a, **_k):
            return "   "  # SEM_DADOS_PARA_RESPONDER

        assert await _ferramenta(responder)("x") == ponte.SEM_RESPOSTA
        assert ponte.SEM_RESPOSTA != ponte.AVARIOU

    @pytest.mark.asyncio
    async def test_e_uma_excepcao_tambem(self):
        async def responder(*_a, **_k):
            raise RuntimeError("o motor explodiu")

        assert await _ferramenta(responder)("x") == ponte.AVARIOU

    @pytest.mark.asyncio
    async def test_uma_pergunta_vazia_nao_corre_SQL(self):
        """Acontece se o modelo chamar a ferramenta sem argumento."""
        chamou = False

        async def responder(*_a, **_k):
            nonlocal chamou
            chamou = True
            return "x"

        assert await _ferramenta(responder)("   ") == ponte.SEM_RESPOSTA
        assert not chamou, "correu um SQL ao calhas por uma pergunta vazia"

    @pytest.mark.parametrize("frase", ["AVARIOU", "SEM_RESPOSTA"])
    def test_as_duas_frases_dizem_ao_modelo_o_que_fazer(self, frase):
        """São instruções, não respostas.

        O que o modelo recebe no `toolResult` não é lido em voz alta — é
        contexto para ele formular. Uma frase que não lhe diga o que
        fazer deixa-o a inventar.
        """
        texto = getattr(ponte, frase)
        assert len(texto) > 40
        assert "pessoa" in texto.lower()
