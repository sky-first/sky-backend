# -*- coding: utf-8 -*-
"""Uma corrida de agente responde SEMPRE no fio.

> *"aparece a Sky está a trabalhar nisso, a resposta aparece aqui, mas nada
> acontece. Isso já fazem vários minutos. É bem provável que alguma coisa
> travou"* — Lucas, 31/08/2026

---

**Nada tinha travado.** Fui ver na base local, com o worker a correr:

    agent_executions.status = 'completed'
    findings_count          = 0
    mensagens na conversa   = 0

A corrida acabou em menos de um segundo e **não escreveu uma linha**. Do lado
da app isso lê-se como «ainda a trabalhar», indistinguível de uma avaria — e
foi exactamente essa a leitura dele.

A causa era um `if`: a resposta só era publicada no fio
``if finding_da_corrida is not None``. Uma corrida sem nada a assinalar ficava
calada para sempre.

**Um agente é uma pergunta que se repete, e uma pergunta tem sempre
resposta.** «Olhei e não há nada a assinalar» é uma resposta; silêncio não é.

---

**E a primeira versão desta correcção mentia.**

Escrevia «não há nada a assinalar» mesmo quando o orquestrador tinha
devolvido um erro — uma frase tranquilizadora a dizer que os dados não tinham
nada, quando o que houve foi uma avaria nossa. Manda a pessoa procurar no
sítio errado. São duas frases porque são duas coisas.
"""
from __future__ import annotations

import inspect

from src.workers import agent_worker


def _fonte() -> str:
    return inspect.getsource(agent_worker)


class TestRespondeSempre:
    def test_o_if_que_calava_a_corrida_desapareceu(self):
        fonte = _fonte()
        assert "if finding_da_corrida is not None:\n                try:" not in fonte

    def test_ha_um_caminho_para_o_caso_sem_achado(self):
        """O `else` do achado — o que estava em falta."""
        fonte = _fonte()
        i = fonte.index("if finding_da_corrida is not None:")
        bloco = fonte[i : i + 2500]
        assert "else:" in bloco
        assert "NADA_A_ASSINALAR" in bloco

    def test_e_publica_pelo_mesmo_caminho(self):
        """`post_agent_answer` nos dois ramos: um sítio só a decidir como
        uma corrida fala."""
        fonte = _fonte()
        i = fonte.index("if finding_da_corrida is not None:")
        bloco = fonte[i : i + 2500]
        assert bloco.count("await post_agent_answer(") >= 3


class TestUmaAvariaNaoSeDisfarcaDeSilencio:
    def test_ha_uma_frase_so_para_a_avaria(self):
        assert hasattr(agent_worker, "NAO_CONSEGUI")

    def test_e_nao_e_a_mesma_do_nada_a_assinalar(self):
        """Se fossem iguais, a distinção existia no código e não no ecrã."""
        assert agent_worker.NAO_CONSEGUI != agent_worker.NADA_A_ASSINALAR

    def test_a_avaria_diz_que_o_problema_e_nosso(self):
        """Sem isto a pessoa vai procurar o defeito nos dados dela."""
        assert "nosso" in agent_worker.NAO_CONSEGUI.lower()

    def test_e_o_nada_a_assinalar_promete_voltar(self):
        """Um agente que não encontrou nada não é um agente que desistiu."""
        assert "próxima" in agent_worker.NADA_A_ASSINALAR.lower()

    def test_a_escolha_usa_o_detector_de_erros_que_ja_existia(self):
        """`_looks_like_orchestrator_error` já era usado para não envenenar
        o `last_answer` da corrida seguinte. É o mesmo sinal."""
        fonte = _fonte()
        i = fonte.index("if finding_da_corrida is not None:")
        assert "_looks_like_orchestrator_error(answer)" in fonte[i : i + 2500]


class TestUmaCorridaQueFALHOUNaoDizQueNaoEncontrouNada:
    """A mentira tranquilizadora, outra vez — e vista em produção.

    > «a mensagem que está dando é que analisou e não encontrou nada?
    >  ... eu acho que realmente deu algum erro, porque se há dados
    >  deveria retornar não?»
    > — Lucas, 09/10/2026

    Tinha razão. No fio dele, na base de produção:

        14:41 → 15:06, de 5 em 5 min, SEIS corridas
        agent_executions.status  = failed
        agent_executions.error   = «1 ligação(ões) sem resposta … HTTPStatus»
        e no fio: «Olhei agora e não há nada a assinalar.»

    A verificação de «falharam TODAS as ligações» **existia** — mas vinte
    linhas DEPOIS da escrita no fio. O fio dizia que tinha olhado e não
    havia nada, e só a seguir é que a execução era marcada `failed`.

    O comentário dessa verificação já dizia, desde 22/08, que isto não
    podia acontecer: «é uma frase tranquilizadora para dizer que nem uma
    consulta chegou a ser feita». Estava certo e no sítio errado.
    """

    def test_decide_se_falhou_ANTES_de_escrever_no_fio(self):
        fonte = _fonte()
        decide = fonte.index("falhou_por_completo = ")
        escreve = fonte.index(
            "if falhou_por_completo:\n                    await post_agent_answer"
        )
        assert decide < escreve, (
            "a decisão tem de vir antes da escrita — ao contrário, o fio "
            "diz «não há nada» e só depois se descobre que falhou tudo"
        )

    def test_e_a_mensagem_e_a_da_AVARIA(self):
        fonte = _fonte()
        i = fonte.index("if falhou_por_completo:")
        bloco = fonte[i : i + 400]
        assert "NAO_CONSEGUI" in bloco
        assert "NADA_A_ASSINALAR" not in bloco

    def test_e_leva_chave_para_as_repetidas_se_juntarem(self):
        """Seis falhas seguidas passam a ler-se «6 vezes», numa mensagem.

        Foi a outra queixa: «as várias mensagens repetidas? deveria
        agrupá-las». A `chave_de_texto` é o que faz a colagem — e o
        caminho da avaria não a tinha.
        """
        fonte = _fonte()
        i = fonte.index("if falhou_por_completo:")
        assert 'chave_de_texto="agent_could_not_run"' in fonte[i : i + 400]

    def test_as_duas_decisoes_usam_a_MESMA_variavel(self):
        """O que impede a próxima divergência.

        Era precisamente a divergência entre as duas — a mensagem a dizer
        uma coisa e a execução outra — que mentia.
        """
        fonte = _fonte()
        assert fonte.count("falhou_por_completo") >= 3
        assert "if ligacoes_falhadas and not respostas_por_ligacao:" not in fonte, (
            "a condição voltou a estar escrita duas vezes — e duas cópias "
            "divergem à primeira mudança"
        )
