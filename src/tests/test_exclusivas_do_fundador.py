"""O que é do fundador do cliente não é do admin.

Apanhado a 18/08/2026 comparando as duas vias de autorização nas contas de teste
do sandbox: para `permissions.edit`, o `Authorization.can()` dizia **não** ao
admin e o `assert_permission()` — o que as rotas usam — dizia **sim**.

A causa era banal e é o padrão que mais custa: **duas listas com a mesma
verdade**. A tabela de regras marcava quatro chaves como `owner_only`; a lista
dentro do `RBACService` tinha três. A que faltava era `permissions.edit` — ou
seja, um admin do cliente podia editar a matriz de permissões e **dar-se a si
próprio o que quisesse**.

A correcção deriva a lista da tabela de regras. Estes testes guardam a derivação
e o resultado, porque só o resultado não impede que alguém volte a escrever a
lista à mão.
"""

from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import ForbiddenError
from src.models.user import User
from src.services.authorization import PERMISSION_RULES
from src.services.rbac_service import RBACService


def _pessoa(papel: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{papel}@empresa-de-mentira.pt",
        role=papel,
        password_hash="x",
        name=papel.title(),
    )


def _exclusivas_declaradas() -> set[str]:
    return {c for c, (_e, exigido) in PERMISSION_RULES.items() if exigido == "owner_only"}


def test_permissions_edit_e_do_fundador():
    """A chave que estava a faltar, nomeada.

    Se um dia sair de `owner_only` na tabela de regras, este teste falha e
    obriga a decisão a ser deliberada em vez de silenciosa.
    """
    assert "permissions.edit" in _exclusivas_declaradas()


@pytest.mark.asyncio
async def test_o_admin_nao_edita_a_matriz_de_permissoes(db_session):
    """O caso concreto: um admin não se promove a si próprio."""
    admin = _pessoa("admin")
    db_session.add(admin)
    await db_session.flush()

    with pytest.raises(ForbiddenError):
        await RBACService(db_session).assert_permission(admin, "permissions.edit")


@pytest.mark.asyncio
async def test_o_admin_continua_recusado_em_todas_as_exclusivas(db_session):
    """Todas, não só a que apareceu.

    Percorrer a lista derivada significa que uma chave nova marcada
    `owner_only` fica protegida sem ninguém se lembrar de a acrescentar aqui.
    """
    admin = _pessoa("admin")
    db_session.add(admin)
    await db_session.flush()
    svc = RBACService(db_session)

    for chave in sorted(_exclusivas_declaradas()):
        with pytest.raises(ForbiddenError, match="SuperAdmin|denied"):
            await svc.assert_permission(admin, chave)


@pytest.mark.asyncio
async def test_o_fundador_passa_nas_exclusivas(db_session):
    """A outra metade: fechar de mais é tão mau como abrir.

    O fundador tem de continuar a poder transferir a posse e mexer na matriz,
    senão o cliente fica sem quem administre.
    """
    fundador = _pessoa("super_admin")
    db_session.add(fundador)
    await db_session.flush()
    svc = RBACService(db_session)

    for chave in sorted(_exclusivas_declaradas()):
        await svc.assert_permission(fundador, chave)  # não levanta


@pytest.mark.asyncio
async def test_o_member_tambem_nao(db_session):
    membro = _pessoa("member")
    db_session.add(membro)
    await db_session.flush()
    svc = RBACService(db_session)

    for chave in sorted(_exclusivas_declaradas()):
        with pytest.raises(ForbiddenError):
            await svc.assert_permission(membro, chave)
