"""O texto que vai para a síntese de voz não leva marcação.

A app já limpava o markdown antes de falar — mas só no caminho LOCAL, que é o
da web. **Num telemóvel quem sintetiza é o servidor**, e aí a resposta ia crua:
o que se ouvia era a Sky a ler os asteriscos do negrito e os hífenes das
listas.

Foi assim que o defeito sobreviveu à primeira correcção: foi corrigido no lado
que não é usado onde ele foi ouvido.

O texto do ECRÃ continua a ir em markdown — quem lê quer a formatação, quem
ouve não. É essa a distinção que estes testes fixam.
"""

from src.services.speech_text import speech_text


class TestSemMarcacao:
    def test_tira_o_negrito_que_era_lido_como_asteriscos(self):
        assert speech_text("**Julho fechou 4% acima do orçamento.**") == (
            "Julho fechou 4% acima do orçamento."
        )

    def test_tira_o_italico_e_o_codigo(self):
        assert speech_text("isto é *importante* e `SELECT 1` também") == (
            "isto é importante e SELECT 1 também"
        )

    def test_tira_os_cardinais_dos_titulos(self):
        assert speech_text("## Resumo\nTudo bem.") == "Resumo\nTudo bem."

    def test_tira_as_citacoes(self):
        assert speech_text("> Isto é do trimestre passado") == "Isto é do trimestre passado"

    def test_le_o_texto_do_link_e_nao_o_endereco(self):
        assert speech_text("ver o [relatório de Julho](https://exemplo.pt/a/b)") == (
            "ver o relatório de Julho"
        )

    def test_nao_le_um_bloco_de_codigo(self):
        # Seriam minutos de sintaxe ditos ao telefone.
        saida = speech_text("Foi assim:\n```sql\nSELECT * FROM vendas;\n```\nE deu 12.")
        assert "SELECT" not in saida
        assert "Foi assim:" in saida
        assert "E deu 12." in saida


class TestPontuacaoDaFala:
    def test_as_listas_mantem_cada_item_na_sua_linha(self):
        # A diferença que importa: sem as quebras, o motor lê seis números de
        # enfiada, sem respirar.
        md = "- Receita: 412.300 €\n- Variação: +4,1%\n- Maior: Sul"
        assert speech_text(md) == "Receita: 412.300 €\nVariação: +4,1%\nMaior: Sul"

    def test_nao_deixa_mais_do_que_uma_linha_em_branco(self):
        # Três quebras não fazem uma pausa maior — fazem um silêncio esquisito.
        assert speech_text("Primeiro.\n\n\n\nSegundo.") == "Primeiro.\n\nSegundo."


class TestCasosLimite:
    def test_aguenta_vazio_e_nulo(self):
        assert speech_text("") == ""
        assert speech_text(None) == ""

    def test_texto_sem_marcacao_passa_igual(self):
        assert speech_text("Julho fechou acima do orçamento.") == (
            "Julho fechou acima do orçamento."
        )

    def test_aplicar_duas_vezes_da_o_mesmo(self):
        md = "**Resumo**\n- um\n- dois"
        assert speech_text(speech_text(md)) == speech_text(md)


class TestEspelhaOCliente:
    """Os dois lados têm de dar o MESMO resultado.

    Se divergirem, a mesma resposta soa diferente conforme o utilizador esteja
    na web ou no telemóvel — o género de divergência que ninguém descobre até
    um cliente a ouvir. Os casos abaixo estão copiados um a um do
    `apps/mobile/src/components/speechText.test.ts`.
    """

    CASOS = [
        ("Sobre **Oi**:", "Sobre Oi:"),
        ("isto é *importante* e `SELECT 1` também", "isto é importante e SELECT 1 também"),
        ("- Receita: 412.300 €\n- Variação: +4,1%", "Receita: 412.300 €\nVariação: +4,1%"),
        ("## Resumo\nTudo bem.", "Resumo\nTudo bem."),
        ("> Isto é do trimestre passado", "Isto é do trimestre passado"),
        ("Primeiro.\n\n\n\nSegundo.", "Primeiro.\n\nSegundo."),
        ("Julho fechou acima do orçamento.", "Julho fechou acima do orçamento."),
    ]

    def test_mesmo_resultado_que_a_app(self):
        for entrada, esperado in self.CASOS:
            assert speech_text(entrada) == esperado, entrada
