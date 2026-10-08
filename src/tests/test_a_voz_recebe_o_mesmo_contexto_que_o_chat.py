# -*- coding: utf-8 -*-
"""A voz mandava ao motor metade do que o chat manda.

> «testei o livetalk e está muito fraco… em quase todas as vezes não
>  está encontrando dados, apenas para perguntas muito básicas»
> — Lucas, 08/10/2026

── O diagnóstico, em três números ──────────────────────────────────

O chat escrito manda 11 campos ao `sky-ai`. A voz mandava 5. As duas
diferenças que explicam o sintoma:

**`connection_ids`.** O chat manda TODAS as ligações do projecto e o
`sky-ai` funde os catálogos de tabelas num só `AgentConfig`. A voz
mandava uma. Num projecto com Flota, Operaciones e Carga, uma pergunta
que atravesse duas não tem tabela onde aterrar: o orquestrador devolve
`IMPOSSIBLE` e o formatador responde `NO_DATA_FOUND` — que é, palavra
por palavra, «não está encontrando dados».

**`instructions`.** O glossário e as métricas certificadas entram no
prompt de ESCOLHA DE TABELAS. Sem eles o motor não sabe que «vacío de
retorno» é uma coisa — define-se por uma ausência e não existe em
coluna nenhuma. Só acerta quando a pergunta calha usar o nome físico.
É, literalmente, «apenas para perguntas muito básicas».

── O que este teste protege ────────────────────────────────────────

Não a qualidade da resposta — isso mede-se com a voz na mão. Protege a
PARIDADE: que a voz não volte a ficar atrás do chat sem que alguém dê
por isso. Foi assim que chegou aqui — o chat ganhou campos ao longo de
meses e a voz ficou na versão de quando nasceu.
"""
from __future__ import annotations

import inspect

from src.api.v1 import ai as rota_do_chat
from src.api.v1 import voice


def _fonte_da_voz() -> str:
    return inspect.getsource(voice._voice_answer)  # noqa: SLF001


class TestOsCamposQueFaltavam:
    def test_a_voz_manda_todas_as_ligacoes_do_projecto(self):
        fonte = _fonte_da_voz()
        assert "connection_ids=todas" in fonte, (
            "a voz voltou a mandar uma ligação só — uma pergunta que "
            "atravesse duas devolve «não encontrei dados»"
        )

    def test_e_o_conjunto_ja_estava_calculado(self):
        """O detalhe que dói: a informação estava ali e era deitada fora.

        O `permitidas` existe desde que a voz passou a respeitar o
        projecto. Usava-se para VALIDAR a escolha e descartava-se.
        """
        fonte = _fonte_da_voz()
        assert "permitidas" in fonte
        assert "todas = sorted(permitidas)" in fonte

    def test_a_voz_manda_o_glossario(self):
        fonte = _fonte_da_voz()
        assert "render_knowledge_for_prompt" in fonte
        assert "instructions=instrucoes" in fonte

    def test_e_o_glossario_nao_e_obrigatorio(self):
        """Um reforço, não um requisito.

        Se o carregador falhar, a resposta é pior — não inexistente. Uma
        excepção aqui calava o turno inteiro por causa de um extra.
        """
        fonte = _fonte_da_voz()
        i = fonte.index("render_knowledge_for_prompt")
        assert "except Exception" in fonte[i : i + 600]

    def test_o_modo_pessoal_tambem(self):
        """Sem projecto, o chat pede as ligações de demonstração todas.

        Cinco esquemas contra um — a voz via um quinto dos dados.
        """
        assert "_get_user_dataset_connection_ids" in _fonte_da_voz()


class TestOTurnoMudo:
    def test_uma_escolha_fora_do_projecto_ja_nao_cala(self):
        """O defeito que fazia a voz calar-se por completo.

        `_get_first_active_connection_for_space` cai na «primeira
        ligação do utilizador» quando não encontra nada no projecto — e
        essa pode estar fora dele. A voz anulava-a e devolvia silêncio.

        Para quem pertence só a uma EQUIPA (e não ao projecto), o
        repositório não encontra a ligação: silêncio garantido, enquanto
        o chat responde à mesma pessoa.
        """
        fonte = _fonte_da_voz()
        assert "conn_id = sorted(permitidas)[0]" in fonte


class TestOPrazoDoTurno:
    def test_o_turno_espera_dois_segundos_e_meio(self):
        """1,6 s cortava quem hesita a meio de uma pergunta longa.

        É o tecto que a literatura de endpointing dinâmico usa. É um
        remendo honesto — o certo é decidir pelo fim da FRASE e não pelo
        cronómetro — e erra menos vezes do que 1,6.
        """
        assert voice.SILENCIO_QUE_FECHA_O_TURNO == 2.5

    def test_e_continua_a_ser_configurável_pelos_testes(self):
        # Ao nível do módulo: um teste que espera de verdade é um teste
        # que alguém acaba por apagar.
        assert isinstance(voice.SILENCIO_QUE_FECHA_O_TURNO, float)


class TestAParidadeComOChat:
    """O contrapeso, e o que impede a próxima divergência.

    Cada campo que o chat manda ao motor e a voz não é uma diferença de
    qualidade à espera de acontecer. Esta lista é a fronteira: quando o
    chat ganhar um campo novo, isto falha e obriga a decidir.
    """

    #: Campos que o chat manda e a voz também tem de mandar.
    PARIDADE = ("connection_ids", "instructions", "is_personal")

    #: Campos que o chat manda e a voz NÃO manda, com a razão.
    SO_DO_CHAT = {
        "selected_context": "a voz não tem selector de contexto no ecrã",
        "crew_ids": "o sky-ai recalcula-os e sem eles fica mais LARGO, não mais estreito",
        "agent_mode": "a voz não corre dentro de um fio de agente",
        "selected_datasets": "não há escolha de conjuntos na voz",
        "sql_instructions": "é do modo SQL dos agentes",
        "authorized_tables": "nenhum dos dois manda",
    }

    def test_a_voz_manda_tudo_o_que_tem_de_mandar(self):
        fonte = _fonte_da_voz()
        em_falta = [c for c in self.PARIDADE if f"{c}=" not in fonte]
        assert not em_falta, f"a voz deixou de mandar: {em_falta}"

    def test_e_o_chat_continua_a_mandar_os_mesmos(self):
        """Se o chat deixar de mandar um, a paridade deixa de fazer
        sentido — e é melhor dar por isso aqui do que ir atrás."""
        fonte = inspect.getsource(rota_do_chat)
        em_falta = [c for c in self.PARIDADE if f"{c}=" not in fonte]
        assert not em_falta, f"o chat deixou de mandar: {em_falta}"

    def test_cada_diferenca_que_fica_tem_razao(self):
        curtas = [c for c, razao in self.SO_DO_CHAT.items() if len(razao) < 20]
        assert not curtas, f"diferenças sem razão escrita: {curtas}"
