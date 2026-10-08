# -*- coding: utf-8 -*-
"""Interromper a Sky e ouvi-la acabar a frase.

── O defeito de hoje ───────────────────────────────────────────────

Quando a pessoa interrompe, o cliente cala o que está a tocar e manda
`barge_in`. Parece completo, e não é: os pedaços de TTS que **já tinham
saído do servidor** continuam a chegar depois disso, e tocam.

Numa ligação rápida não se nota — há poucos bytes em trânsito. Numa
ligação de telemóvel, com uma resposta de cinco segundos já em voo,
nota-se muito: interrompe-se e ela continua.

── A correcção, e porque funciona ─────────────────────────────────

O servidor responde ao `barge_in` com um `discard_audio`, que entra no
MESMO socket. Logo vai **atrás** dos pedaços que já lá estavam — o
WebSocket garante a ordem — e quando chega ao cliente já chegou tudo o
que havia para descartar. Uma linha, e o problema fecha-se de vez em
vez de ficar a depender da velocidade da rede.

── E é a peça que o Nova Sonic exige ──────────────────────────────

Lá a interrupção é detectada pelo MODELO, não pela pessoa
(`{"interrupted": true}` aparece sozinho no fluxo). Sem um evento para
o dizer ao cliente, o barge-in que vem de graça ouve-se pior do que não
o ter: a Sky é interrompida no servidor e continua a falar no
auscultador.

Ver `docs/a-voz-medida-nova-sonic.md`, caso S5.
"""
from __future__ import annotations

import inspect

from src.api.v1 import voice


def _fonte_do_ws() -> str:
    return inspect.getsource(voice.voice_session_ws)


class TestOServidorPedeODescarte:
    def test_existe_maneira_de_o_pedir(self):
        fonte = _fonte_do_ws()
        assert "discard_audio" in fonte, (
            "o servidor não tem como dizer ao cliente para descartar o "
            "áudio — sem isso a interrupção depende da velocidade da rede"
        )

    def test_e_o_barge_in_pede_o(self):
        """O sítio que importa hoje."""
        fonte = _fonte_do_ws()
        i = fonte.index('action == "barge_in"')
        # Na mesma pernada do `elif`, antes do `elif` seguinte.
        pernada = fonte[i : fonte.index('elif action in ("stop"', i)]
        assert "descartar_audio()" in pernada, (
            "o `barge_in` não pede o descarte — o áudio que já ia a "
            "caminho continua a chegar e a tocar"
        )

    def test_e_continua_a_mudar_o_estado(self):
        """O descarte não substitui o estado; acrescenta-se-lhe.

        Sem o `user_speaking`, o cliente descartava o áudio e ficava a
        achar que a Sky ainda estava a falar.
        """
        fonte = _fonte_do_ws()
        i = fonte.index('action == "barge_in"')
        pernada = fonte[i : fonte.index('elif action in ("stop"', i)]
        assert 'state("user_speaking")' in pernada


class TestOFormatoDoEvento:
    def test_e_um_type_como_os_outros(self):
        """O protocolo é um `type` por linha de JSON, e isto segue-o.

        Importa para a compatibilidade: um cliente mais antigo cai no
        `default` do `switch` e ignora o que não conhece. Continua a
        tocar como hoje — pior, mas não partido.
        """
        fonte = inspect.getsource(voice.voice_session_ws)
        assert '{"type": "discard_audio"}' in fonte, (
            "o evento tem de ser um `type` simples, para um cliente "
            "antigo o poder ignorar sem rebentar"
        )

    def test_nao_leva_dados_nenhuns(self):
        """Um evento sem campos não tem como ficar incompatível.

        Se algum dia precisar de um motivo ou de um id, acrescenta-se um
        campo OPCIONAL — nunca obrigatório, senão os clientes já
        instalados deixam de o entender.
        """
        fonte = inspect.getsource(voice.voice_session_ws)
        i = fonte.index('{"type": "discard_audio"}')
        linha = fonte[i : fonte.index("\n", i)]
        assert linha.strip() == '{"type": "discard_audio"})', (
            f"o evento ganhou campos: {linha.strip()}"
        )
