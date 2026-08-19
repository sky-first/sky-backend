"""Quem pode dar que papel a quem.

Encontrado em produção, no cliente `sandbox`, com a conta `teste.admin@`:

    PUT /api/v1/users/{o_meu_id}  {"role": "super_admin"}  ->  200
    role agora: super_admin

Um admin promovia-se a fundador com uma chamada. Isso torna inútil tudo o que
seja exclusivo do fundador — `billing.manage`, `tenant.delete`,
`tenant.transfer_ownership`, `permissions.edit` — porque o caminho para lá
estava aberto a quem já era admin. Corrigi `permissions.edit` no dia anterior
e não fechei esta porta, que é a que interessa.

O segundo caminho, `PUT /users/{id}/permissions`, validava contra a lista
``["admin", "user", "viewer"]``: recusava `member` (o papel normal de toda a
gente) e aceitava `viewer`, que nem é papel de cliente — é de espaço/equipa.
"""

from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import ForbiddenError
from src.core.permissions import (
    PAPEIS_DE_CLIENTE_VALIDOS,
    validar_atribuicao_de_papel,
)
from src.models.user import User


def _pessoa(papel: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{papel}@empresa-de-mentira.pt",
        role=papel,
        password_hash="x",
        name=papel.title(),
    )


def test_o_admin_nao_nomeia_fundadores():
    """O caso concreto, nomeado."""
    with pytest.raises(ForbiddenError, match="fundador"):
        validar_atribuicao_de_papel(_pessoa("admin"), "super_admin")


def test_o_fundador_nomeia_fundadores():
    """A outra metade: um cliente tem de poder ter mais do que um fundador,
    senão a saída de uma pessoa deixa o cliente órfão."""
    validar_atribuicao_de_papel(_pessoa("super_admin"), "super_admin")


def test_o_admin_continua_a_nomear_admins_e_members():
    """Fechar de mais partia a gestão de equipa do dia-a-dia."""
    for papel in ("admin", "member"):
        validar_atribuicao_de_papel(_pessoa("admin"), papel)


@pytest.mark.parametrize("legado", ["owner", "user"])
def test_os_papeis_legados_deixam_de_ser_aceites(legado):
    """`owner` e `user` já foram convertidos pela migração de 03/06.

    Continuar a aceitá-los na escrita fabrica contas meio privilegiadas: o
    frontend trata `owner` como fundador (`lib/rbac/can.ts`) e o
    `is_tenant_admin` não, por isso a pessoa vê o menu e leva 403. Foi
    exactamente o que aconteceu à conta de teste `teste.owner@`.
    """
    with pytest.raises(ForbiddenError, match="inválido"):
        validar_atribuicao_de_papel(_pessoa("super_admin"), legado)


def test_viewer_nao_e_papel_de_cliente():
    """`viewer` é papel de espaço/equipa. A lista à mão do
    `update_user_permissions` aceitava-o e recusava `member`."""
    assert "viewer" not in PAPEIS_DE_CLIENTE_VALIDOS
    assert "member" in PAPEIS_DE_CLIENTE_VALIDOS
    with pytest.raises(ForbiddenError):
        validar_atribuicao_de_papel(_pessoa("super_admin"), "viewer")
