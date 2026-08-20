"""O agente devolve a conversa onde escreve.

A app mostra "Abrir conversa" quando o agente tem `conversation_id`, e o
comentário dela descreve esse botão como *"a mais usada de todas"*. O campo
existe na tabela desde sempre — mas o `AgentResponse` não o devolvia, por isso
**todos** os agentes apareciam como "Ainda não falou", mesmo os que já tinham
corrido e produzido achados. O botão nunca chegava a existir.

Apanhado a 20/08/2026 comparando, rota a rota, o que a API devolve com o tipo
que a app declara — o mesmo método que destapou o `connection_id` das ligações
de um projeto e o `user` aninhado dos membros de equipa nesse dia. Nenhum dos
três dava erro: falhavam em silêncio, no ecrã.
"""

from __future__ import annotations

import pytest

from src.models.agent import Agent
from src.schemas.agent import AgentListResponse, AgentResponse

#: Os **dois** schemas que devolvem um agente.
#:
#: Corrigi só o `AgentResponse`, promovi, e o botão continuou a não aparecer:
#: o ecrã dos agentes lê a lista, e a lista usa o `AgentListResponse`. Só se
#: viu ao verificar em produção com uma conta a sério. Este teste passa a
#: percorrer os dois — se amanhã nascer um terceiro, tem de entrar aqui.
SCHEMAS = [AgentResponse, AgentListResponse]


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda s: s.__name__)
def test_o_campo_existe_na_resposta(schema):
    assert "conversation_id" in schema.model_fields


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda s: s.__name__)
def test_e_opcional_porque_um_agente_novo_ainda_nao_falou(schema):
    """Um agente acabado de criar não tem conversa — e isso não é um erro.

    Se o campo fosse obrigatório, criar um agente passava a rebentar na
    serialização.
    """
    campo = schema.model_fields["conversation_id"]
    assert not campo.is_required()
    assert campo.default is None


def test_a_coluna_existe_mesmo_na_tabela():
    """Sem isto, o campo do schema seria uma promessa vazia: devolvia sempre
    `None` e o botão continuava a não aparecer."""
    assert "conversation_id" in Agent.__table__.columns


def test_a_resposta_carrega_o_valor_da_linha():
    """De ponta a ponta, com um objecto a sério."""
    import uuid
    from datetime import datetime, timezone

    conversa = uuid.uuid4()
    agora = datetime.now(timezone.utc)
    resposta = AgentResponse.model_validate(
        {
            "id": uuid.uuid4(),
            "name": "Vigia das vendas",
            "scope": "space",
            "archetype": "custom",
            "frequency": "daily",
            "scope_id": str(uuid.uuid4()),
            "status": "active",
            "conversation_id": conversa,
            "created_at": agora,
            "updated_at": agora,
        }
    )
    assert resposta.conversation_id == conversa
