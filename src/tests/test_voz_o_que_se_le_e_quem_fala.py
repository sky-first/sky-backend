# -*- coding: utf-8 -*-
"""O que se lê e quem fala no Live Talk — o teste do Lucas a 10/10.

> «Lucía e Sérgio… nenhuma das duas é a que está a ser usada»
> «escreve "veintisiete mil"… o correto era apresentar um número»
> «é preciso ter o ponto de interrogação»
> «pergunto que dia é hoje. E ele não tem essa informação»
> «eu mal acabo de falar, e ele até cortou»
"""
from __future__ import annotations

import pytest

from src.services import voz_sessao_sonic as sonic
from src.services import vozes
from src.services.numeros_falados import em_algarismos
from src.services.pontuacao import pontuar_pergunta


class TestNumerosEmAlgarismos:
    @pytest.mark.parametrize(
        "dito,lingua,lido",
        [
            # Medido no Sonic real a 10/10.
            (
                "lo más parecido es el número de pedidos, que son ciento cincuenta y ocho mil trescientos cuarenta.",
                "es",
                "lo más parecido es el número de pedidos, que son 158.340.",
            ),
            (
                "La empresa cuenta con veintisiete mil personas.",
                "es",
                "La empresa cuenta con 27.000 personas.",
            ),
            (
                "Hoy es sábado diez de octubre de dos mil veintiséis.",
                "es",
                "Hoy es sábado 10 de octubre de 2026.",
            ),
            (
                "Temos vinte e sete mil pessoas e cento e vinte lojas.",
                "pt",
                "Temos 27.000 pessoas e 120 lojas.",
            ),
            ("A margem subiu quatro vírgula cinco por cento.", "pt", "A margem subiu 4,5 %."),
            ("Facturaron un millón doscientos mil euros.", "es", "Facturaron 1.200.000 euros."),
            ("We have one hundred and twenty five stores.", "en", "We have 125 stores."),
        ],
    )
    def test_numero_por_extenso_vira_algarismos(self, dito, lingua, lido):
        assert em_algarismos(dito, lingua) == lido

    @pytest.mark.parametrize(
        "dito,lingua",
        [
            ("Uno de los clientes compró más.", "es"),  # artigo, não número
            ("Entre tres y cuatro tiendas.", "es"),  # dois números, não 7
            ("Um dos pedidos atrasou.", "pt"),
            ("El margen sube tres puntos.", "es"),
        ],
    )
    def test_o_que_nao_e_numero_fica(self, dito, lingua):
        assert em_algarismos(dito, lingua) == dito

    def test_uma_legenda_nunca_parte(self):
        assert em_algarismos("", "es") == ""
        assert em_algarismos("hola", "de") == "hola"


class TestPerguntaPontuada:
    @pytest.mark.parametrize(
        "dito,lingua,lido",
        [
            ("cuántos clientes tengo", "es", "¿Cuántos clientes tengo?"),
            ("qué día es hoy?", "es", "¿Qué día es hoy?"),
            ("Qué día es hoy.", "es", "¿Qué día es hoy?"),
            ("quantos clientes temos", "pt", "Quantos clientes temos?"),
            ("how many stores do we have", "en", "How many stores do we have?"),
        ],
    )
    def test_pergunta_leva_interrogacao(self, dito, lingua, lido):
        assert pontuar_pergunta(dito, lingua) == lido

    @pytest.mark.parametrize("dito", ["Hola, soy Lucas", "tenho uma reunião amanhã", "que bom"])
    def test_o_que_nao_e_pergunta_nao_leva(self, dito):
        assert not pontuar_pergunta(dito, "es").endswith("?")


class TestQuemFala:
    def test_a_voz_escolhida_e_a_que_responde(self):
        assert sonic.voz_do_locale("es", "carlos") == "carlos"
        assert sonic.voz_do_locale("es", "lupe") == "lupe"
        assert sonic.voz_do_locale("pt", "leo") == "leo"

    def test_as_escolhas_antigas_mantem_o_genero(self):
        # «Sergio» era um homem do Polly; quem o escolheu ouvia a `lupe`.
        assert sonic.voz_do_locale("es", "sergio") == "carlos"
        assert sonic.voz_do_locale("es", "lucia") == "lupe"
        assert sonic.voz_do_locale("pt", "thiago") == "leo"

    def test_um_id_desconhecido_cai_na_voz_da_lingua(self):
        assert sonic.voz_do_locale("es", "nao-existe") == "lupe"
        assert sonic.voz_do_locale("xx", None) == "matthew"

    def test_o_recado_soa_ao_mesmo_genero(self):
        assert vozes.polly_da_sonic("carlos") == "Pedro"
        assert vozes.polly_da_sonic("lupe") == "Lupe"

    def test_cada_voz_tem_amostra_gravada_com_o_sonic(self):
        import os

        pasta = os.path.join(os.path.dirname(__file__), "..", "assets", "vozes")
        for lista in vozes.CATALOGO.values():
            for v in lista:
                assert os.path.exists(os.path.join(pasta, f"{v.id}.wav")), v.id


class TestOQueASkySabe:
    def test_sabe_a_data_e_a_hora(self):
        texto = sonic.instrucao_de_sistema("es")
        assert "Europe/Madrid" in texto
        assert "/20" in texto  # dd/mm/aaaa

    def test_o_fuso_da_app_manda(self):
        assert "Atlantic/Canary" in sonic.instrucao_de_sistema("es", "Atlantic/Canary")

    def test_um_fuso_invalido_nao_parte_a_voz(self):
        assert "UTC" in sonic.agora_em("es", "Lua/Base")

    def test_diz_o_resultado_tal_e_qual(self):
        assert "TAL E QUAL" in sonic.instrucao_de_sistema("pt")


@pytest.mark.asyncio
async def test_o_fim_de_turno_espera_mais():
    from src.services import voz_fala_a_fala as falada

    assert falada.SENSIBILIDADE_DO_FIM_DE_TURNO == "LOW"
