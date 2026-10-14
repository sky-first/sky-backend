# -*- coding: utf-8 -*-
"""O castelhano da voz soa a Espanha.

Decisão do Lucas (14/10/2026), depois de ouvir gravações reais do Sonic:
a `lupe` e o `carlos` são es-US e soam a América Latina — nota 5–6 mesmo
com instrução de sotaque. As poliglotas `tiffany` e `matthew`, com a
instrução de Espanha, tiveram 8–9. Em castelhano passam a ser essas, e quem
tinha a `lupe`/`carlos` guardada passa à do mesmo género sem fazer nada.

O que tem de ser verdade:
  * o ecrã só oferece tiffany + matthew em castelhano;
  * uma preferência antiga (lupe/carlos) ouve a nova do mesmo género —
    na sessão do Sonic, na cascata (Polly) e na pré-escuta;
  * a instrução de Espanha vai na sessão castelhana e SÓ nela — a
    `matthew` em inglês continua americana;
  * o recado de espera em castelhano é um Polly de Espanha (Lucia/Sergio),
    e em inglês continua a ser o inglês;
  * a pré-escuta castelhana é a gravação castelhana, não a inglesa.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from src.services import voz_recado as recado
from src.services import voz_sessao_sonic as sonic
from src.services import vozes
from src.tests.test_a_sessao_sonic_no_socket import _SessaoFalsa, _Socket, _start, _User, _Ctx


class TestOEcra:
    def test_em_castelhano_oferece_tiffany_e_matthew(self):
        es = vozes.catalogo_como_json()["Español"]
        assert [(v["id"], v["gender"]) for v in es] == [("tiffany", "f"), ("matthew", "m")]

    def test_lupe_e_carlos_ja_nao_se_oferecem_em_lado_nenhum(self):
        ids = {v["id"] for lista in vozes.catalogo_como_json().values() for v in lista}
        assert not ids & {"lupe", "carlos"}

    def test_as_outras_linguas_nao_mudaram(self):
        j = vozes.catalogo_como_json()
        assert [v["id"] for v in j["Portuguese"]] == ["ines", "leo"]
        assert [v["id"] for v in j["English"]] == ["matthew", "tiffany"]


class TestQuemTinhaALupeOuOCarlos:
    @pytest.mark.parametrize("guardada,nova", [("lupe", "tiffany"), ("carlos", "matthew")])
    def test_a_sessao_do_sonic_fala_com_a_nova(self, guardada, nova):
        assert sonic.voz_do_locale("es", guardada) == nova
        assert sonic.voz_do_locale("es-ES", guardada) == nova

    @pytest.mark.parametrize("guardada,polly", [("lupe", "Lucia"), ("carlos", "Sergio")])
    def test_a_cascata_fala_com_um_polly_de_espanha(self, guardada, polly):
        assert vozes.voz_polly("Español", guardada) == polly

    def test_noutra_lingua_cai_na_omissao_dessa_lingua(self):
        # A `lupe` nunca foi portuguesa: em português continua a Inês.
        assert sonic.voz_do_locale("pt", "lupe") == "ines"

    def test_sem_escolha_o_castelhano_e_a_tiffany(self):
        assert sonic.voz_do_locale("es") == "tiffany"


class TestOSotaque:
    def test_a_sessao_castelhana_pede_espanha(self):
        texto = sonic.instrucao_de_sistema("es")
        assert texto.startswith("Eres una voz de España.")
        assert "distinción" in texto
        assert "Nunca uses acento latinoamericano" in texto
        assert "vosotros" in texto
        # O resto da instrução continua lá.
        assert "consultar_dados" in texto

    @pytest.mark.parametrize("locale", ["pt", "en", "xx", ""])
    def test_as_outras_linguas_NAO(self, locale):
        texto = sonic.instrucao_de_sistema(locale)
        assert "España" not in texto
        assert "latinoamericano" not in texto

    @pytest.mark.asyncio
    async def test_chega_a_sessao_que_se_abre(self, monkeypatch):
        """Não chega a função saber: a sessão aberta tem de levar a instrução
        e a voz nova, a partir do `start` que a app manda."""
        abertas = []
        sessao = _SessaoFalsa()

        def criar(**kw):
            abertas.append(kw)
            return sessao

        monkeypatch.setattr(sonic.falada, "SessaoFalada", criar, raising=True)

        async def responder(*_a, **_k):
            return "x"

        async def guardar(**_k):
            return "conv-1"

        async def cliente():
            return object()

        s = _Socket([_start(locale="es", voice="carlos"), {"type": "websocket.disconnect"}])
        await asyncio.wait_for(
            sonic.servir(
                s,
                user=_User(),
                ctx=_Ctx(),
                responder=responder,
                persistir=guardar,
                abrir_cliente=cliente,
            ),
            timeout=5,
        )
        assert abertas, "a sessão nem se abriu"
        assert abertas[0]["voz"] == "matthew"
        assert abertas[0]["instrucao"].startswith("Eres una voz de España.")

    @pytest.mark.asyncio
    async def test_a_matthew_em_ingles_continua_americana(self, monkeypatch):
        abertas = []
        sessao = _SessaoFalsa()
        monkeypatch.setattr(
            sonic.falada, "SessaoFalada", lambda **kw: (abertas.append(kw), sessao)[1], raising=True
        )

        async def responder(*_a, **_k):
            return "x"

        async def guardar(**_k):
            return "conv-1"

        async def cliente():
            return object()

        s = _Socket([_start(locale="en", voice="matthew"), {"type": "websocket.disconnect"}])
        await asyncio.wait_for(
            sonic.servir(
                s,
                user=_User(),
                ctx=_Ctx(),
                responder=responder,
                persistir=guardar,
                abrir_cliente=cliente,
            ),
            timeout=5,
        )
        assert abertas[0]["voz"] == "matthew"
        assert "España" not in abertas[0]["instrucao"]


class TestORecadoDeEspera:
    @pytest.mark.parametrize(
        "voz,locale,polly",
        [
            ("tiffany", "es", "Lucia"),
            ("matthew", "es", "Sergio"),
            ("tiffany", "en", "Ruth"),
            ("matthew", "en", "Matthew"),
            ("ines", "pt", "Ines"),
        ],
    )
    def test_e_o_polly_da_lingua_da_conversa(self, voz, locale, polly):
        assert recado.voz_do_recado(voz, locale) == polly

    @pytest.mark.asyncio
    async def test_a_sintese_pede_a_lucia_em_castelhano(self, monkeypatch):
        pedidos = []

        class _Corpo:
            def __init__(self):
                self.lido = False

            def read(self, _n):
                if self.lido:
                    return b""
                self.lido = True
                return b"\x00\x00"

        class _Polly:
            def synthesize_speech(self, **kw):
                pedidos.append(kw)
                return {"AudioStream": _Corpo()}

        import boto3

        monkeypatch.setattr(boto3, "client", lambda *_a, **_k: _Polly())
        enviados = []

        async def enviar(b):
            enviados.append(b)

        ok = await recado.dizer(enviar, "Déjeme mirarlo.", "tiffany", locale="es")
        assert ok and enviados
        assert pedidos[0]["VoiceId"] == "Lucia"


class TestAPreEscuta:
    async def _ouvir(self, voice: str, language: str) -> bytes:
        from src.api.v1.voice import ouvir_voz

        r = await ouvir_voz(voice=voice, language=language, current_user=None)
        return r.body

    def _ficheiro(self, nome: str) -> bytes:
        p = os.path.join(os.path.dirname(__file__), "..", "assets", "vozes", f"{nome}.wav")
        with open(p, "rb") as f:
            return f.read()

    @pytest.mark.asyncio
    async def test_a_tiffany_castelhana_nao_e_a_inglesa(self):
        es = await self._ouvir("tiffany", "Español")
        en = await self._ouvir("tiffany", "English")
        assert es == self._ficheiro("tiffany_es")
        assert en == self._ficheiro("tiffany")
        assert es != en

    @pytest.mark.asyncio
    @pytest.mark.parametrize("guardada,amostra", [("lupe", "tiffany_es"), ("carlos", "matthew_es")])
    async def test_quem_tinha_a_antiga_ouve_a_nova(self, guardada, amostra):
        assert await self._ouvir(guardada, "Español") == self._ficheiro(amostra)

    def test_a_gravacao_leva_o_sotaque(self):
        """A pré-escuta tem de soar ao que responde: o script que a grava
        pede o mesmo sotaque que a sessão."""
        p = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts", "gravar_amostras_das_vozes.py"
        )
        with open(p, encoding="utf-8") as f:
            fonte = f.read()
        assert "sotaque_de(lingua)" in fonte
        assert "v.amostra" in fonte


def test_o_json_do_catalogo_nao_leva_o_ficheiro_da_amostra():
    # O `amostra` é um pormenor do servidor; a app pede pela voz e pela língua.
    for lista in vozes.catalogo_como_json().values():
        for v in lista:
            assert set(v) <= {"id", "name", "gender", "accent"}
    json.dumps(vozes.catalogo_como_json())
