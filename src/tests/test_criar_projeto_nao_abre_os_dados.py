"""Criar um projeto não pode dar acesso a ligar dados.

Encontrado em produção a 19/08, minutos depois de eu próprio abrir o
`spaces.create` a toda a gente:

    POST /api/v1/spaces        (como member)  ->  201
    POST /api/v1/connections   (como member)  ->  201   ← não podia

A cadeia é curta e não a vi ao fazer a mudança:

  1. qualquer pessoa cria um projeto;
  2. quem cria um projeto fica **dono** dele (`SpaceMember role="owner"`);
  3. o `RBACService` empilha o papel de projeto por cima do de member;
  4. `DEFAULT_ROLE_PERMISSIONS["owner"]` traz `connections.create: True`.

Ou seja: "qualquer um cria um projeto" virou "qualquer um cunha ligações de
dados" — exactamente a porta que o modelo de 18/08 manda manter fechada, e
que dá sentido ao pedido de acesso.

A correcção não é fechar a criação de projetos outra vez: é dizer que **o
papel de projeto não concede o que é decisão do cliente**.
"""

from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import ForbiddenError
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.services.authorization import PERMISSION_RULES
from src.services.rbac_service import (
    CHAVES_QUE_O_PROJETO_NAO_CONCEDE,
    DEFAULT_ROLE_PERMISSIONS,
    RBACService,
)


async def _member_dono_do_seu_projeto(db) -> tuple[User, Space]:
    """Um member que criou o seu projeto — e por isso é dono dele."""
    pessoa = User(
        id=uuid.uuid4(),
        email=f"m-{uuid.uuid4().hex[:6]}@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name="Membro",
    )
    db.add(pessoa)
    await db.flush()

    projeto = Space(name=f"P {uuid.uuid4().hex[:6]}", created_by=pessoa.id)
    db.add(projeto)
    await db.flush()
    db.add(SpaceMember(space_id=projeto.id, user_id=pessoa.id, role="owner"))
    await db.commit()
    return pessoa, projeto


@pytest.mark.asyncio
async def test_dono_do_proprio_projeto_nao_cunha_ligacoes(db_session):
    """O caso exacto que apareceu em produção — **sem** `space_id`.

    O `POST /connections` não indica projeto nenhum: cunha-se uma ligação e
    só depois se liga a um projeto. Sem `space_id`, o `assert_permission`
    caía no "melhor papel do utilizador em qualquer lado", e como a pessoa
    passou a ter um projeto seu, esse papel virou `owner`.

    Passar `space_id` aqui esconderia o defeito, que foi o meu primeiro erro
    a escrever este teste: com projeto indicado ele passava mesmo com a
    correcção removida.
    """
    pessoa, _projeto = await _member_dono_do_seu_projeto(db_session)
    svc = RBACService(db_session)

    for chave in CHAVES_QUE_O_PROJETO_NAO_CONCEDE:
        with pytest.raises(ForbiddenError):
            await svc.assert_permission(pessoa, chave)


@pytest.mark.asyncio
async def test_nem_com_o_proprio_projeto_indicado(db_session):
    """E também não pela outra porta, com o projeto no pedido."""
    pessoa, projeto = await _member_dono_do_seu_projeto(db_session)
    svc = RBACService(db_session)

    for chave in CHAVES_QUE_O_PROJETO_NAO_CONCEDE:
        with pytest.raises(ForbiddenError):
            await svc.assert_permission(pessoa, chave, space_id=projeto.id)


@pytest.mark.asyncio
async def test_o_ecra_tambem_nao_lhe_mostra_o_botao(db_session):
    """A terceira porta: o frontend pergunta as permissões efectivas.

    Se elas dissessem que sim, a pessoa via o botão e levava 403 ao carregar
    — o padrão de "mostrar o que vai ser recusado" que já custou caro."""
    pessoa, projeto = await _member_dono_do_seu_projeto(db_session)
    efectivas = await RBACService(db_session).get_effective_permissions(
        pessoa, space_id=projeto.id
    )
    for chave in CHAVES_QUE_O_PROJETO_NAO_CONCEDE:
        assert efectivas.permissions.get(chave) is False, chave


@pytest.mark.asyncio
async def test_mas_continua_a_conduzir_o_seu_projeto(db_session):
    """A outra metade — fechar de mais deixava o projeto inútil.

    Quem cria um projeto tem de o poder gerir: convidar gente, criar equipas,
    e operar as ligações que já lhe foram autorizadas. O que não pode é
    autorizar-se a si próprio dados novos.
    """
    pessoa, projeto = await _member_dono_do_seu_projeto(db_session)
    svc = RBACService(db_session)

    for chave in (
        "spaces.members.manage",
        "crews.create",
        "connections.sync",
        "connections.view",
    ):
        await svc.assert_permission(pessoa, chave, space_id=projeto.id)


def test_as_duas_vias_de_autorizacao_concordam():
    """A divergência entre elas já custou três defeitos esta semana."""
    for chave in CHAVES_QUE_O_PROJETO_NAO_CONCEDE:
        escopo, exigido = PERMISSION_RULES[chave]
        assert (escopo, exigido) == ("tenant", "admin_or_above"), (
            f"{chave} devia ser decisão do cliente, não do projeto"
        )


def test_a_lista_cobre_as_tres_operacoes_de_cunhar():
    """Se alguém acrescentar `connections.import` e se esquecer da lista, o
    buraco reabre em silêncio. Isto ao menos fixa o que já se sabe."""
    assert set(CHAVES_QUE_O_PROJETO_NAO_CONCEDE) == {
        "connections.create",
        "connections.edit",
        "connections.delete",
    }
    # E o papel de dono de projeto continua a *declarar* que pode — é o
    # empilhamento que passa a ser corrigido, não a tabela. Se isto mudar,
    # a correcção passou a estar noutro sítio e este teste tem de saber.
    assert DEFAULT_ROLE_PERMISSIONS["owner"]["connections.create"] is True
