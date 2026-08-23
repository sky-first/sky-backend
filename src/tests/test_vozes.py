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

    def test_o_portugues_e_de_portugal(self):
        # A voz que la estava, «Camila», e pt-BR. Foi mais um sitio onde a app
        # dizia «portugues» e entregava outra coisa.
        assert all(v.lingua == "pt-PT" for v in CATALOGO["Portuguese"])

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
        assert voz_polly("Portuguese", "cristiano") == "Cristiano"
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

        assert _polly_voice("Portuguese", "cristiano") == "Cristiano"

    def test_lixo_nao_chega_ao_polly(self):
        from src.services.voice_aws import _polly_voice

        assert _polly_voice("English", "qualquer-coisa") in {
            v.polly for v in vozes_de("English")
        }
