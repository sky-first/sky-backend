# -*- coding: utf-8 -*-
"""Um projeto novo não vem com agentes — e deixou de o parecer.

> *"ja vem com agentes? Pois aparece que tem 6 agente que estao a procura e
> nao encontraram nada"* — Lucas, a gravar uma demonstração para a Remax

Não vinham. O ecrã pedia a lista de agentes **sem âmbito**, e a rota, a quem
é administrador do cliente, devolve nesse caso o inquilino inteiro. Os seis
eram de outros projetos, e diziam que não encontravam nada porque não estavam
sequer a olhar para ali.

**Porque é que pedir pelo projeto não bastava.** Um agente é sempre criado ao
nível da equipa (`scope="crew"`, decisão de Junho). Um pedido literal por
`scope="space"` comparava texto com texto e devolvia zero — o que empurrava
os ecrãs de volta para o pedido sem âmbito, que era o problema.

O projeto é a fronteira; a equipa é uma etiqueta. Um pedido pelo projeto tem
de trazer o que as equipas dele criaram — as que lá nasceram e as que foram
convidadas.
"""
from __future__ import annotations

import inspect

from src.repositories import agent as repo_agentes


def _fonte() -> str:
    return inspect.getsource(repo_agentes.AgentRepository.list_by_scope)


class TestPedirPeloProjeto:
    def test_o_ramo_do_projeto_existe(self):
        assert 'scope == "space" and scope_id' in _fonte()

    def test_um_identificador_mal_formado_nao_derruba_a_lista(self):
        """`space_id` e uma coluna UUID; `Agent.scope_id` e texto.

        Comparar a coluna com uma cadeia que nao e UUID rebenta dentro do
        SQLAlchemy (``'str' object has no attribute 'hex'``) em vez de dar
        lista vazia. Uma lista de agentes nao pode ir abaixo por causa de um
        identificador mal formado vindo do cliente — e foi assim que a CI
        apanhou isto, com dois testes que passam `scope_id="s1"`.
        """
        fonte = _fonte()
        assert "projeto = UUID(str(scope_id))" in fonte
        assert "except (ValueError, AttributeError, TypeError)" in fonte

    def test_traz_as_equipas_convidadas_e_as_que_la_nasceram(self):
        """Só um dos dois deixava metade dos agentes de fora.

        Uma equipa pode pertencer ao projeto (`Crew.space_id`) ou ter sido
        convidada para ele (`space_crews`). São caminhos diferentes para o
        mesmo sítio, e o de fora não é menos do projeto do que o de dentro.
        """
        fonte = _fonte()
        assert "SpaceCrew.space_id == projeto" in fonte
        assert "Crew.space_id == projeto" in fonte

    def test_o_texto_e_comparado_com_texto(self):
        """`Agent.scope_id` é `String` e as chaves das equipas são `UUID`.

        Sem o `cast` o Postgres recusa a comparação — e o erro só aparecia
        em produção, porque em SQLite passa.
        """
        assert "cast(SpaceCrew.crew_id, String)" in _fonte()
        assert "cast(Crew.id, String)" in _fonte()

    def test_um_agente_do_proprio_projeto_continua_a_contar(self):
        """Se algum dia alguém gravar um agente com `scope="space"`."""
        assert '(Agent.scope == "space") & (Agent.scope_id == str(scope_id))' in _fonte()

    def test_os_outros_ambitos_nao_mudaram(self):
        """`personal` e `crew` seguem o caminho simples de sempre."""
        fonte = _fonte()
        assert "query = query.where(Agent.scope == scope)" in fonte
        assert "query = query.where(Agent.scope_id == scope_id)" in fonte
