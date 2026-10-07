# -*- coding: utf-8 -*-
"""A voz calava-se e destruía a razão.

> «o live talk em si está funcionando. Eu falo e ele pega a minha voz e
>  escreve. O que não está funcionando é que o Sky fica pensando»
> — Lucas, 06/10/2026

── O que o `test_voz_nao_fica_muda` já protegia ────────────────────

Que uma excepção **que sobe** do `do_turn` não deixa a sessão calada:
apanha-se, manda-se `turn_failed`, devolve-se a palavra. Continua a
valer, e está lá.

── O que faltava, e é o que fazia o silêncio ───────────────────────

O `_voice_answer` tinha, no fim, isto:

    except Exception:
        return ""

Duas consequências:

1. **Nada subia.** A falha virava `""`, o `do_turn` fazia ``if answer:``
   e saltava o bloco inteiro. Nem texto, nem voz, nem `turn_failed`. O
   guarda do teste de Agosto nunca chegava a disparar, porque não havia
   excepção nenhuma para apanhar.

2. **A razão era destruída.** Sem registo não há como saber se foi o
   motor, a ligação ou o cliente — e sem isso a correcção seguinte é um
   palpite. Foi o que me aconteceu: cheguei aqui com um sintoma e sem
   uma linha de log para o explicar.

── E o `""` não é sempre uma avaria ────────────────────────────────

Há um silêncio legítimo: o projeto não tem ligações que esta pessoa
alcance. Aí calar É a resposta certa — cair na «primeira ligação» foi
um defeito corrigido antes. Por isso os dois casos passam a ser
valores diferentes, e não o mesmo nada.
"""
from __future__ import annotations

import inspect

from src.api.v1 import voice


def _fonte_da_resposta() -> str:
    return inspect.getsource(voice._voice_answer)  # noqa: SLF001


def _fonte_do_turno() -> str:
    fonte = inspect.getsource(voice.voice_session_ws)
    i = fonte.index("async def do_turn")
    return fonte[i : fonte.index("async def consume_transcripts", i)]


class TestOsDoisNadaSaoDiferentes:
    def test_ha_um_valor_para_o_silencio_legitimo(self):
        assert voice.SEM_DADOS_PARA_RESPONDER == ""

    def test_e_outro_para_a_avaria(self):
        assert voice.FALHOU_A_RESPOSTA is None

    def test_e_nao_sao_o_mesmo(self):
        # Se fossem, não havia como a app dizer «não consegui» em vez de
        # ficar calada — que é o defeito inteiro.
        assert voice.SEM_DADOS_PARA_RESPONDER is not voice.FALHOU_A_RESPOSTA


class TestARazaoFicaEscrita:
    def test_o_except_regista_em_vez_de_engolir(self):
        """`except Exception: return ""` sem log era onde a razão morria."""
        fonte = _fonte_da_resposta()
        i = fonte.rindex("except Exception:")
        resto = fonte[i:]
        assert "logger.exception" in resto, (
            "o `except` voltou a engolir a falha — sem registo, o próximo "
            "relato deste defeito é outra vez um palpite"
        )

    def test_e_leva_o_cliente_e_o_projeto(self):
        """Um log sem o cliente não serve: há vários, e falham um de cada vez."""
        fonte = _fonte_da_resposta()
        i = fonte.rindex("except Exception:")
        resto = fonte[i:]
        assert "space_id" in resto
        assert "slug" in resto

    def test_um_erro_do_motor_e_lido(self):
        """O evento `error` do SSE era ignorado.

        Só `chunk` e `answer` eram olhados. O motor dizia que tinha
        falhado, e a razão vinha escrita no evento que ninguém lia.
        """
        fonte = _fonte_da_resposta()
        assert 'ev.get("type") == "error"' in fonte

    def test_e_uma_resposta_vazia_sem_erro_tambem_conta_como_avaria(self):
        """Nem erro, nem texto: é avaria nossa, não conclusão sobre os dados.

        Sem isto, o caso mais provável de todos — o motor a responder 200
        com nada — voltava a ser silêncio indistinguível.
        """
        fonte = _fonte_da_resposta()
        assert "não devolveu texto" in fonte


class TestOTurnoDizQueFalhou:
    def test_a_falha_de_dentro_segue_o_mesmo_caminho_das_outras(self):
        """Um caminho só para «o turno falhou».

        Dois divergem à primeira mudança, e o segundo é o que ninguém
        testa. A falha de dentro do `_voice_answer` levanta e cai no
        `except` que já existia.
        """
        corpo = _fonte_do_turno()
        assert "FALHOU_A_RESPOSTA" in corpo
        assert "raise _RespostaFalhou()" in corpo

    def test_e_o_except_continua_la(self):
        # O guarda de Agosto. Sem ele, levantar aqui seria trocar um
        # silêncio por outro.
        corpo = _fonte_do_turno()
        assert "except Exception:" in corpo
        assert '"turn_failed"' in corpo

    def test_o_silencio_legitimo_continua_a_calar(self):
        """O contrapeso.

        «Este projeto não tem dados que você alcance» não é uma avaria, e
        gritar `turn_failed` de cada vez que alguém fala num projeto vazio
        seria pior do que o defeito.
        """
        corpo = _fonte_do_turno()
        i = corpo.index("FALHOU_A_RESPOSTA")
        # A comparação é por identidade com o valor da avaria, e não uma
        # verificação de vazio — `""` tem de continuar a passar ao largo.
        assert "resposta is FALHOU_A_RESPOSTA" in corpo[i - 60 : i + 60]
