"""O `generate_sql` deixa de ler os metadados por cima das permissões.

Encontrado a 18/08/2026 ao preparar a mudança da fronteira de dados para o
projeto. A rota `/ai/generate-sql` recebe o UUID da ligação **no pedido** e, com
ele, ia buscar a metadata e mandava para o motor **todas** as tabelas da ligação
— sem passar pelo `PermissionService`.

Não devolve linhas, devolve SQL. Mas devolve também o mapa: nomes de tabelas e
de colunas de qualquer ligação do cliente, a qualquer pessoa autenticada que
adivinhasse ou copiasse um UUID. E ver que uma coisa existe é precisamente o que
a permissão devia estar a esconder — foi por isso que o Unity Catalog teve de
inventar um privilégio `BROWSE` à parte.

O que estes testes fixam:

1. Quem alcança a ligação continua a gerar SQL.
2. Quem não a alcança leva recusa, **com a mesma mensagem** de quando a ligação
   não existe — uma recusa que distinga os dois casos é um oráculo para
   descobrir o catálogo.
"""

from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import ForbiddenError, ServiceUnavailableError
from src.models.connection import DataConnection
from src.models.user import User
from src.schemas.ai import GenerateSQLRequest
from src.services.ai_service import AIService


def _pessoa(nome: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{nome.lower()}@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name=nome,
    )


async def _cenario(db):
    """A Ana tem uma ligação. O Bruno não tem nada."""
    ana, bruno = _pessoa("Ana"), _pessoa("Bruno")
    db.add_all([ana, bruno])
    await db.flush()

    erp = DataConnection(
        id=uuid.uuid4(),
        name="ERP da Ana",
        connector_id="postgres",
        config={},
        created_by=ana.id,
    )
    db.add(erp)
    await db.flush()
    return ana, bruno, erp


@pytest.mark.asyncio
async def test_o_bruno_nao_arranca_o_esquema_da_ligacao_da_ana(db_session, monkeypatch):
    e_ana, bruno, erp = await _cenario(db_session)
    svc = AIService(db_session)
    # O motor está configurado — a recusa tem de vir da permissão, não da falta
    # de serviço, senão o teste passava pela razão errada.
    monkeypatch.setattr(svc, "real_ai", object())

    pedido = GenerateSQLRequest(question="quanto vendemos?", knowledge=[str(erp.id)])

    with pytest.raises((ForbiddenError, ServiceUnavailableError)) as caiu:
        await svc.generate_sql(bruno.id, pedido)

    # A mensagem não pode confirmar que a ligação existe.
    assert "No data connection available" in str(caiu.value)
    assert str(erp.id) not in str(caiu.value)
    assert "ERP" not in str(caiu.value)


@pytest.mark.asyncio
async def test_uma_ligacao_que_nao_existe_recusa_igual(db_session, monkeypatch):
    """Mesma frase para "não existe" e para "não é tua".

    Se as duas respostas diferirem, quem sonda descobre o catálogo por
    eliminação, sem nunca ter acesso a nada.
    """
    _ana, bruno, erp = await _cenario(db_session)
    svc = AIService(db_session)
    monkeypatch.setattr(svc, "real_ai", object())

    inexistente = GenerateSQLRequest(question="quanto vendemos?", knowledge=[str(uuid.uuid4())])
    alheia = GenerateSQLRequest(question="quanto vendemos?", knowledge=[str(erp.id)])

    with pytest.raises((ForbiddenError, ServiceUnavailableError)) as a:
        await svc.generate_sql(bruno.id, inexistente)
    with pytest.raises((ForbiddenError, ServiceUnavailableError)) as b:
        await svc.generate_sql(bruno.id, alheia)

    assert str(a.value) == str(b.value)
