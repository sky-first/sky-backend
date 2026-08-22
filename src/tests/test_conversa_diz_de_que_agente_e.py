"""O fio de um agente diz que é dele.

Um insight é uma conversa, e a conversa de um agente é a MESMA em todas as
corridas — é ali que ele responde todos os dias. Quem abre esse fio tem de
conseguir chegar ao agente para o configurar.

A ligação entre os dois existe só num sentido: `agents.conversation_id`. O
que o cliente desenha é a conversa, e a conversa não sabia nada do agente —
portanto não havia como pôr lá o botão que leva à configuração sem adivinhar.
"""

from __future__ import annotations

import inspect

from src.schemas.conversation import ConversationResponse


def test_o_detalhe_da_conversa_tem_lugar_para_o_agente():
    campos = ConversationResponse.model_fields
    assert "agent_id" in campos
    assert "agent_name" in campos


def test_sem_agente_os_campos_ficam_vazios():
    """A maioria das conversas não é de agente nenhum, e essas não podem
    passar a exigir um campo novo."""
    assert ConversationResponse.model_fields["agent_id"].default is None
    assert ConversationResponse.model_fields["agent_name"].default is None


def test_o_endpoint_preenche_os_campos():
    """O guarda que importa.

    Ter os campos no schema não os enche — e um campo que vem sempre a `None`
    é pior do que não existir: o cliente desenha a app à volta dele e não
    aparece nada, sem erro nenhum a dizer porquê.
    """
    from src.api.v1 import conversations

    fonte = "\n".join(
        l
        for l in inspect.getsource(conversations).splitlines()
        if not l.lstrip().startswith("#")
    )
    assert "agent_for_conversation(db, conversation_id)" in fonte
    assert "resposta.agent_id = agente.id" in fonte
    assert "resposta.agent_name = agente.name" in fonte


def test_a_lista_nao_paga_isto():
    """Só o detalhe.

    A lista devolve dezenas de fios; uma consulta por linha para descobrir o
    agente de cada um sairia cara e não serve para nada — o botão vive dentro
    da conversa, não na linha da lista.
    """
    from src.api.v1 import conversations

    fonte = inspect.getsource(conversations)
    # A chamada aparece uma vez, e é a do detalhe.
    assert fonte.count("agent_for_conversation(db, conversation_id)") == 1
