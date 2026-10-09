# -*- coding: utf-8 -*-
"""A legenda ao vivo escreve enquanto se fala — e nunca cala a conversa.

O Nova Sonic não manda transcrição parcial: medido a 09/10/2026, duas
falas dão exactamente dois `textOutput` com `role: USER`, cada um no fim
da frase. Por isso o ecrã ficava com três pontinhos durante toda a fala.

A legenda vem do Transcribe, a correr em paralelo. **É um extra**, e a
regra que estes testes protegem é essa: se ela falhar, perde-se a
legenda e mais nada.
"""
from __future__ import annotations

import asyncio

import pytest

from src.services import voz_legenda_ao_vivo as legenda_mod


class TestALingua:
    def test_segue_o_locale_da_sessao(self):
        assert legenda_mod.lingua_do_locale("pt") == "pt-PT"
        assert legenda_mod.lingua_do_locale("es") == "es-ES"
        assert legenda_mod.lingua_do_locale("en") == "en-US"

    def test_um_locale_desconhecido_nao_rebenta(self):
        """Ficar sem legenda é mau; rebentar a sessão é pior."""
        assert legenda_mod.lingua_do_locale("zz") == legenda_mod._LINGUA_DE_RECURSO
        assert legenda_mod.lingua_do_locale("") == legenda_mod._LINGUA_DE_RECURSO
        assert legenda_mod.lingua_do_locale(None) == legenda_mod._LINGUA_DE_RECURSO  # type: ignore[arg-type]

    def test_aceita_um_locale_completo(self):
        assert legenda_mod.lingua_do_locale("es-ES") == "es-ES"
        assert legenda_mod.lingua_do_locale("pt-BR") == "pt-PT"


class TestOInterruptor:
    def test_ligada_por_omissao(self, monkeypatch):
        monkeypatch.delenv("VOICE_LIVE_CAPTION", raising=False)
        assert legenda_mod.esta_ligada()

    @pytest.mark.parametrize("valor", ["0", "false", "off", "nao", "NÃO", " 0 "])
    def test_desliga_se_sem_uma_entrega(self, monkeypatch, valor):
        """O interruptor existe para a tirar do caminho à pressa."""
        monkeypatch.setenv("VOICE_LIVE_CAPTION", valor)
        assert not legenda_mod.esta_ligada()


class TestUmaAvariaNaoCalaAConversa:
    @pytest.mark.asyncio
    async def test_se_nao_abrir_fica_morta_e_calada(self, monkeypatch):
        """Sem Transcribe não há legenda — e não há excepção."""
        legenda = legenda_mod.LegendaAoVivo("pt")
        # É o que acontece quando a biblioteca não está, ou a AWS recusa.
        await legenda.abrir()
        assert not legenda.viva
        # E continua a aceitar áudio sem se queixar, que é o que a
        # sessão vai fazer a cada pedaço do microfone.
        await legenda.ouvir(bytes(320))

    @pytest.mark.asyncio
    async def test_um_erro_a_meio_desliga_a_legenda_e_mais_nada(self):
        """O caso que interessa: ela estava viva e deixou de estar."""

        class _FluxoQueRebenta:
            class input_stream:  # noqa: N801
                @staticmethod
                async def send_audio_event(audio_chunk):  # noqa: ANN001
                    raise RuntimeError("a ligacao caiu")

        legenda = legenda_mod.LegendaAoVivo("es")
        legenda._fluxo = _FluxoQueRebenta()
        legenda._viva = True

        await legenda.ouvir(bytes(320))  # não levanta

        assert not legenda.viva
        # E não tenta outra vez a cada pedaço: uma legenda que insiste
        # enche os registos e não melhora nada.
        await legenda.ouvir(bytes(320))

    @pytest.mark.asyncio
    async def test_audio_vazio_nao_vai_a_lado_nenhum(self):
        enviados = []

        class _Fluxo:
            class input_stream:  # noqa: N801
                @staticmethod
                async def send_audio_event(audio_chunk):  # noqa: ANN001
                    enviados.append(audio_chunk)

        legenda = legenda_mod.LegendaAoVivo("pt")
        legenda._fluxo = _Fluxo()
        legenda._viva = True

        await legenda.ouvir(b"")
        assert enviados == []
        await legenda.ouvir(bytes(320))
        assert len(enviados) == 1


class TestOsParciais:
    @pytest.mark.asyncio
    async def test_saem_pela_ordem_em_que_chegam(self):
        legenda = legenda_mod.LegendaAoVivo("es")
        for t in ["cuántos", "cuántos clientes", "cuántos clientes tengo"]:
            await legenda._fila.put(t)
        await legenda._fila.put(None)

        vistos = [t async for t in legenda.parciais()]
        assert vistos == ["cuántos", "cuántos clientes", "cuántos clientes tengo"]

    @pytest.mark.asyncio
    async def test_fechar_acorda_quem_esta_a_espera(self):
        """Sem isto a tarefa da legenda ficava pendurada no fecho."""
        legenda = legenda_mod.LegendaAoVivo("pt")

        async def _ler():
            return [t async for t in legenda.parciais()]

        leitor = asyncio.create_task(_ler())
        await asyncio.sleep(0)
        await legenda.fechar()
        assert await asyncio.wait_for(leitor, timeout=1) == []


class TestARegiao:
    def test_nao_e_a_do_sonic(self):
        """O Sonic vive em eu-north-1, que NÃO serve streaming de STT.

        Confirmado na API de preços a 09/10/2026: em Estocolmo só há
        `TranscribeAudio` (lote); o `StreamingAudio` é da Irlanda. Pôr a
        legenda na região do Sonic dava uma avaria silenciosa.
        """
        assert legenda_mod.REGIAO != "eu-north-1"
