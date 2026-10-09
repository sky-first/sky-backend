# -*- coding: utf-8 -*-
"""A fala tem de sair com a DURAÇÃO certa no auscultador.

── O defeito ───────────────────────────────────────────────────────

O Nova Sonic devolve áudio a **24 kHz**. Todas as apps já instaladas
tocam a **16 kHz** — o `SAMPLE_RATE` do `WsSpeechAdapter.ts`, posto lá
no tempo da cascata, onde o Polly saía mesmo a 16000.

Mandar 24 kHz a quem toca a 16 kHz faz a fala sair **1,5× mais lenta e
mais grave**. A 09/10/2026 o Lucas ouviu-a e descreveu-a como «MEGA
robotizada». Não era a voz escolhida: era a mesma voz, arrastada.

── Porque é que a asserção é a duração ─────────────────────────────

Contar bytes também apanhava este caso, mas diria pouco a quem lesse o
teste daqui a seis meses. O que se garante é o que se ouve: **um segundo
de fala tem de continuar a durar um segundo** depois de atravessar a
ponte. Seja qual for a conta lá dentro.
"""
from __future__ import annotations

import math
from array import array

from src.services import voz_fala_a_fala as falada
from src.services import voz_ponte_sonic as ponte


def _tom(segundos: float, hz_do_sinal: int, taxa: int) -> bytes:
    """Um tom puro, para se poder medir o que lhe aconteceu."""
    n = int(taxa * segundos)
    a = array("h", (int(12000 * math.sin(2 * math.pi * hz_do_sinal * i / taxa)) for i in range(n)))
    return a.tobytes()


def _duracao(pcm: bytes, taxa: int) -> float:
    return len(pcm) / 2.0 / taxa


class TestAVozNaoSaiArrastada:
    def test_um_segundo_continua_a_durar_um_segundo(self):
        r = ponte.ParaORitmoDaApp(falada.SAIDA_HZ)
        saida = r.alimentar(_tom(1.0, 440, falada.SAIDA_HZ))
        # Tocado a 16 kHz, que é o que a app faz.
        assert abs(_duracao(saida, ponte.HZ_DO_PROTOCOLO) - 1.0) < 0.01

    def test_sem_a_ponte_a_fala_sairia_uma_vez_e_meia_mais_lenta(self):
        """O defeito, escrito. Se alguém tirar a conversão, isto explica-o."""
        bruto = _tom(1.0, 440, falada.SAIDA_HZ)
        arrastada = _duracao(bruto, ponte.HZ_DO_PROTOCOLO)
        assert arrastada > 1.4  # 24000/16000 = 1,5
        r = ponte.ParaORitmoDaApp(falada.SAIDA_HZ)
        assert _duracao(r.alimentar(bruto), ponte.HZ_DO_PROTOCOLO) < 1.01

    def test_aos_pedacos_da_o_mesmo_que_de_uma_vez(self):
        """A emenda entre pedaços não pode perder nem repetir amostras.

        O áudio chega em centenas de pedaços por turno e 24k→16k não é
        inteiro: a cada 3 amostras de entrada saem 2. Tratar cada pedaço
        isoladamente deixava resto, e o resto ouve-se como estalidos.
        """
        inteiro = _tom(0.5, 440, falada.SAIDA_HZ)
        de_uma_vez = ponte.ParaORitmoDaApp(falada.SAIDA_HZ).alimentar(inteiro)

        # Pedaços de tamanho ÍMPAR em amostras, de propósito: é o caso
        # que deixa resto em todas as voltas.
        r = ponte.ParaORitmoDaApp(falada.SAIDA_HZ)
        passo = 101 * 2  # 101 amostras
        aos_bocados = b"".join(
            r.alimentar(inteiro[i : i + passo]) for i in range(0, len(inteiro), passo)
        )

        # Até uma amostra de diferença no fim (o resto que ainda não deu
        # para uma saída). O que não pode haver é deriva.
        assert abs(len(aos_bocados) - len(de_uma_vez)) <= 4

    def test_o_tom_sobrevive(self):
        """Não basta a duração: a fala tem de continuar a ser a fala.

        Uma conversão trocada (saltar amostras em vez de interpolar) dá a
        duração certa e um som sujo. Mede-se a energia: um tom de 440 Hz
        reamostrado continua a ter quase toda a energia que tinha.
        """
        r = ponte.ParaORitmoDaApp(falada.SAIDA_HZ)
        saida = array("h")
        saida.frombytes(r.alimentar(_tom(0.3, 440, falada.SAIDA_HZ)))
        assert len(saida) > 0
        rms = math.sqrt(sum(float(v) * v for v in saida) / len(saida))
        # Um tom de amplitude 12000 tem RMS ~8485. Com margem larga: o
        # que isto apanha é silêncio, ruído ou saturação.
        assert 6000 < rms < 10000, rms

    def test_quando_as_taxas_sao_iguais_nao_se_toca_no_audio(self):
        """Se um dia o modelo falar a 16 kHz, isto sai do caminho."""
        r = ponte.ParaORitmoDaApp(ponte.HZ_DO_PROTOCOLO)
        bruto = _tom(0.1, 440, ponte.HZ_DO_PROTOCOLO)
        assert r.alimentar(bruto) is bruto
