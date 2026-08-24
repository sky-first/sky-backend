"""As vozes da Sky: escolher tem de mudar o que se ouve.

Dois defeitos, e o segundo e o pior:

1. So havia vozes femininas. «Clara» e «Suave» nao diziam se era homem ou
   mulher porque eram as duas mulheres.
2. **A escolha nao chegava ao servidor.** O Polly era escolhido so pela
   lingua, portanto escolher «Suave» em vez de «Clara» nao mudava nada. O
   Lucas foi as definicoes, escolheu, e nao ouviu diferenca — nao ouvia
   porque nao havia.
"""

import pytest

from src.services.vozes import (
    AMOSTRA,
    CATALOGO,
    catalogo_como_json,
    voz_polly,
    vozes_de,
)


class TestOCatalogo:
    def test_cada_lingua_tem_homem_e_mulher(self):
        """**O defeito numero um.** Nao havia por onde escolher uma voz de homem."""
        for lingua, vozes in CATALOGO.items():
            generos = {v.gene for v in vozes}
            assert generos == {"f", "m"}, f"{lingua}: {generos}"

    def test_a_voz_de_omissao_portuguesa_e_de_PORTUGAL(self):
        """A que la estava, «Camila», e pt-BR — a app dizia «portugues» e
        entregava outra coisa.

        A PRIMEIRA de cada lingua e a de omissao, e essa e a Ines (pt-PT).
        A masculina tem de ser brasileira porque nao existe pt-PT masculina
        em neural — ver `TestAsVozesEXISTEM`.
        """
        assert CATALOGO["Portuguese"][0].lingua == "pt-PT"

    def test_duas_vozes_da_mesma_lingua_sao_vozes_DIFERENTES(self):
        """O defeito exacto, em portugues.

        A tabela antiga tinha `Clara -> Camila` e `Suave -> Camila`: dois
        nomes no ecra e uma voz so.
        """
        for lingua, vozes in CATALOGO.items():
            polly = [v.polly for v in vozes]
            assert len(set(polly)) == len(polly), f"{lingua}: {polly}"

    def test_ha_amostra_para_cada_lingua(self):
        assert set(AMOSTRA) == set(CATALOGO)


class TestQualVozFala:
    def test_a_escolha_manda(self):
        assert voz_polly("Portuguese", "thiago") == "Thiago"
        assert voz_polly("Portuguese", "ines") == "Ines"

    def test_sem_escolha_e_a_primeira_da_lingua(self):
        assert voz_polly("Portuguese", None) == vozes_de("Portuguese")[0].polly

    def test_uma_preferencia_velha_nao_fica_sem_som(self):
        """«Clara» e «Suave» estao guardadas nas preferencias de quem ja usou.

        Ficar sem som porque a definicao envelheceu seria pior do que a voz
        nao ser a preferida.
        """
        assert voz_polly("Portuguese", "Clara") == vozes_de("Portuguese")[0].polly
        assert voz_polly("English", "Suave") == vozes_de("English")[0].polly

    def test_uma_lingua_desconhecida_cai_no_ingles(self):
        assert voz_polly("Klingon", None) == vozes_de("English")[0].polly


class TestOQueAAppRecebe:
    def test_o_json_leva_nome_e_genero(self):
        j = catalogo_como_json()
        pt = j["Portuguese"]
        assert {v["gender"] for v in pt} == {"f", "m"}
        assert all(v["name"] and v["id"] for v in pt)

    def test_o_nome_do_polly_nao_viaja(self):
        """O `id` e que viaja, para se poder trocar a voz por baixo.

        Se a app guardasse «Ines» e amanha se mudasse a voz portuguesa, todas
        as preferencias guardadas apontavam para uma voz que ja nao se usa.
        """
        for vozes in catalogo_como_json().values():
            for v in vozes:
                assert "polly" not in v


class TestOMapaAntigoContinuaALigar:
    def test_um_voiceid_cru_passa(self):
        # Os testes e os caminhos antigos mandam o nome do Polly directamente.
        from src.services.voice_aws import _polly_voice

        assert _polly_voice("English", "Ruth") == "Ruth"

    def test_um_id_do_catalogo_e_traduzido(self):
        from src.services.voice_aws import _polly_voice

        assert _polly_voice("Portuguese", "thiago") == "Thiago"

    def test_lixo_nao_chega_ao_polly(self):
        from src.services.voice_aws import _polly_voice

        assert _polly_voice("English", "qualquer-coisa") in {
            v.polly for v in vozes_de("English")
        }


class TestAsVozesEXISTEM:
    """Comparado com o que a AWS diz, e nao com o que eu me lembrava.

    **O defeito.** Escolhi o `Cristiano` para a voz masculina portuguesa a
    olhar para uma lista de cabeca. Ele e standard-only: o Polly recusou com
    «This voice does not support the selected engine: neural» e a pre-escuta
    dava 503. Apanhei-o a carregar no botao em producao.

    O `vozes_neurais_eu_west_1.json` e a resposta do `aws polly
    describe-voices --region eu-west-1`, gravada a 24/08/2026. Nao e uma
    lista que eu escrevi: e o que a AWS respondeu.

    Se a AWS mudar a oferta, este teste acende e regrava-se o ficheiro. O que
    nao pode voltar a acontecer e escolher uma voz de memoria.
    """

    def _verificadas(self):
        import json
        from pathlib import Path

        p = Path(__file__).resolve().parents[1] / "services" / "vozes_neurais_eu_west_1.json"
        return json.loads(p.read_text(encoding="utf-8"))

    def test_todas_as_vozes_do_catalogo_sao_neurais_na_regiao(self):
        verificadas = self._verificadas()
        for lingua, vozes in CATALOGO.items():
            for v in vozes:
                assert v.polly in verificadas, (
                    f"{v.polly} ({lingua}) NAO existe em modo neural em "
                    f"eu-west-1 — foi assim que o Cristiano chegou a producao"
                )

    def test_o_genero_do_catalogo_bate_certo_com_o_da_AWS(self):
        verificadas = self._verificadas()
        mapa = {"f": "Female", "m": "Male"}
        for vozes in CATALOGO.values():
            for v in vozes:
                assert verificadas[v.polly]["genero"] == mapa[v.gene], v.polly

    def test_a_lingua_do_catalogo_bate_certo_com_a_da_AWS(self):
        verificadas = self._verificadas()
        for vozes in CATALOGO.values():
            for v in vozes:
                assert verificadas[v.polly]["lingua"] == v.lingua, v.polly

    def test_o_par_portugues_mistura_sotaques_e_DI_LO(self):
        """Nao ha voz masculina pt-PT neural. O par e Portugal + Brasil.

        Esconder a mistura seria pior do que a mistura: quem escolhe merece
        saber que vai ouvir sotaque brasileiro.
        """
        pt = CATALOGO["Portuguese"]
        assert {v.lingua for v in pt} == {"pt-PT", "pt-BR"}
        assert all(v.sotaque for v in pt), "o sotaque tem de se dizer"

    def test_so_se_diz_o_sotaque_onde_ele_muda(self):
        # Em ingles e espanhol as duas vozes sao da mesma variante; escrever
        # «Estados Unidos» duas vezes por baixo de dois nomes e ruido.
        for lingua in ("English", "Español"):
            assert all(not v.sotaque for v in CATALOGO[lingua]), lingua
