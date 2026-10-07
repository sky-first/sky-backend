# -*- coding: utf-8 -*-
"""18 descobertas na base, e o ecrã a dizer «todo en orden».

> «porque o Hallazgos aparece Todo en orden? cade eles? uma vez que ele
>  criam e abrimos uma vez eles somem?» — Lucas, 07/10/2026

── O que estava mesmo a acontecer ──────────────────────────────────

Confirmado na base de produção, antes de mexer em nada:

    achados                18
    descartados             0
    agentes de equipa      18   (dele, em equipas dele)
    agentes de projecto     3

Nenhuma apagada, nenhuma descartada, todas alcançáveis por ele. O
ecrã pedia `scope="space"` e o endpoint filtrava `Agent.scope ==
"space"` — e um agente nasce sempre ao nível da EQUIPA, por decisão de
2026-06. Dos 21, 18 não passavam.

── A regra já existia, e noutro sítio ──────────────────────────────

O `AgentRepository.list_all` resolve isto desde Junho, escrito para
este mesmo defeito na LISTA de agentes. O resultado era um absurdo
visível: a lista mostrava os agentes e as descobertas deles ficavam
escondidas, porque cada endpoint tinha a sua cópia da pergunta «de
quem é este agente».

Por isso a correcção não é um filtro novo — é tirar o segundo. O
`agentes_do_projeto` é agora a única resposta.
"""
from __future__ import annotations

import inspect
from uuid import uuid4

from src.api.v1 import agents as api_agents
from src.models.agent import Agent
from src.repositories.agent import agentes_do_projeto


class TestUmaRegraSo:
    def test_o_endpoint_usa_a_mesma_funcao_da_lista(self):
        """Duas cópias divergem, e a segunda é a que ninguém testa."""
        fonte = inspect.getsource(api_agents.list_all_insights)
        assert "agentes_do_projeto" in fonte, (
            "o endpoint voltou a ter o seu próprio filtro de âmbito"
        )

    def test_e_a_lista_continua_a_usa_la(self):
        from src.repositories.agent import AgentRepository

        assert "agentes_do_projeto" in inspect.getsource(AgentRepository.list_by_scope)

    def test_ninguem_reescreveu_o_filtro_a_mao(self):
        """O contrapeso: a função pode existir e ninguém a usar.

        A condição de equipa escrita à mão (`Crew.space_id ==`) só pode
        aparecer dentro da própria função.
        """
        fonte = inspect.getsource(api_agents)
        assert "Crew.space_id ==" not in fonte


class TestOQueOFiltroApanha:
    """A condição em si, lida como SQL.

    Sem base de dados: compila-se a expressão e lê-se o texto. É pouco
    elegante e é o que distingue «a função existe» de «a função cobre os
    três casos» — que é exactamente onde a versão anterior falhava.
    """

    def _sql(self) -> str:
        return str(agentes_do_projeto(uuid4()).compile(compile_kwargs={"literal_binds": True}))

    def test_apanha_os_agentes_que_dizem_projecto(self):
        assert "agents.scope = 'space'" in self._sql()

    def test_e_os_das_equipas_do_projecto(self):
        sql = self._sql()
        assert "agents.scope = 'crew'" in sql
        # Nascidas no projecto…
        assert "crews.space_id" in sql
        # …e convidadas para ele. Faltava-me esta no primeiro esboço.
        assert "space_crews" in sql

    def test_compara_texto_com_texto(self):
        """`Agent.scope_id` é TEXTO e as chaves das equipas são UUID.

        Sem o `cast` o Postgres recusa a comparação — e a primeira
        versão que escrevi não o tinha. Teria rebentado em produção, não
        devolvido lista vazia.
        """
        assert "CAST" in self._sql().upper()


class TestOEnderecoMalFormadoNaoRebenta:
    def test_um_scope_id_que_nao_e_uuid_da_lista_vazia(self):
        """E não um 500.

        O `scope_id` vem do cliente. Uma lista de descobertas não pode ir
        abaixo por causa de um identificador mal escrito — é a mesma nota
        que está no repositório, e vale aqui pela mesma razão.
        """
        fonte = inspect.getsource(api_agents.list_all_insights)
        assert "except (ValueError, AttributeError, TypeError)" in fonte


class TestODescartarContinuaAServirParaAlgumaCoisa:
    def test_por_omissao_as_descartadas_ficam_de_fora(self):
        """O contrapeso do arquivo.

        O cliente passou a pedir `include_dismissed=true` para as poder
        mostrar num separador próprio. Se a omissão do servidor mudasse
        também, descartar deixava de limpar fosse o que fosse.
        """
        params = inspect.signature(api_agents.list_all_insights).parameters
        assert params["include_dismissed"].default.default is False

    def test_e_o_servidor_nunca_as_apaga(self):
        """São marcadas, não removidas. É o que permite o arquivo existir."""
        assert hasattr(Agent, "findings")
        from src.models.agent import AgentFinding

        assert hasattr(AgentFinding, "dismissed_at")
