"""Convidar alguém para um workspace que só entra por SSO.

O buraco (14/08/2026): um cliente com ``password: false`` fechava-se sobre si
próprio. O ``create_user`` recusava — "email-and-password invites are
disabled" — e o retorno do SSO, desde o #611, só deixa entrar quem JÁ existe.
Ou seja: ninguém podia ser criado, e quem não fosse criado não entrava. Um
workspace só-SSO nunca mais podia acrescentar um colega, e a mensagem de erro
mandava-o "entrar com o fornecedor de identidade" — coisa que o gate recusa.

A separação que faltava: convidar não é mandar definir uma palavra-passe, é
DAR ACESSO. Num cliente só-SSO isso é provisionar a pessoa e dizer-lhe por que
porta entra.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.user_service import UserService


def _service(auth_methods: dict) -> UserService:
    svc = UserService.__new__(UserService)
    svc.db = MagicMock()

    class _Row:
        def __init__(self, value):
            self._value = value

        def first(self):
            return (self._value,)

    svc.db.execute = AsyncMock(return_value=_Row(auth_methods))
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()

    created = MagicMock(email="nova@cliente.com", id="u-nova")
    svc.user_repo = MagicMock()
    svc.user_repo.get_by_email = AsyncMock(return_value=None)
    svc.user_repo.create = AsyncMock(return_value=created)
    return svc


def _tenant(monkeypatch, slug="alpha"):
    monkeypatch.setattr(
        "src.core.tenant_context.current_tenant", lambda: MagicMock(slug=slug)
    )


class _Caller:
    id = "u-admin"
    name = "Lucas"
    role = "admin"


@pytest.mark.asyncio
async def test_workspace_so_sso_consegue_provisionar(monkeypatch):
    """O caso que estava trancado: o cliente entra só por Google."""
    svc = _service({"password": False, "google": True})
    _tenant(monkeypatch)
    data = MagicMock(email="nova@cliente.com", name="Nova", avatar=None, role="member")

    with (
        patch("src.services.user_service.check_permission", return_value=True),
        patch("src.services.user_service.ensure_default_page_and_space", AsyncMock()),
        patch("src.services.user_service.EmailService") as email_cls,
        patch("src.services.user_service.user_to_response_dict", lambda u: {}),
        patch("src.schemas.user.UserResponse.model_validate", lambda d: d),
    ):
        email = email_cls.return_value
        email.send_sso_access_email.return_value = True
        await svc.create_user(data, _Caller())

    # Provisionada — é a existência da conta que a deixa passar no SSO.
    svc.user_repo.create.assert_awaited()
    kwargs = svc.user_repo.create.await_args.kwargs
    # Sem token de convite: não há palavra-passe nenhuma para definir, e um
    # token que ninguém usa é só uma coisa a expirar.
    assert kwargs["invite_token"] is None
    assert kwargs["invite_expires_at"] is None

    # E recebe o email certo — o de "entra com Google", não o de definir
    # palavra-passe, que a levaria a uma parede.
    email.send_sso_access_email.assert_called_once()
    assert email.send_invite_email.call_count == 0
    assert email.send_sso_access_email.call_args.kwargs["provider_label"] == "Google"


@pytest.mark.asyncio
async def test_workspace_com_password_mantem_o_convite_de_sempre(monkeypatch):
    svc = _service({"password": True, "google": True})
    _tenant(monkeypatch)
    data = MagicMock(email="nova@cliente.com", name="Nova", avatar=None, role="member")

    with (
        patch("src.services.user_service.check_permission", return_value=True),
        patch("src.services.user_service.ensure_default_page_and_space", AsyncMock()),
        patch("src.services.user_service.EmailService") as email_cls,
        patch("src.services.user_service.user_to_response_dict", lambda u: {}),
        patch("src.schemas.user.UserResponse.model_validate", lambda d: d),
    ):
        email = email_cls.return_value
        email.send_invite_email.return_value = True
        await svc.create_user(data, _Caller())

    kwargs = svc.user_repo.create.await_args.kwargs
    assert kwargs["invite_token"] is not None
    assert kwargs["invite_expires_at"] is not None
    email.send_invite_email.assert_called_once()
    assert email.send_sso_access_email.call_count == 0


@pytest.mark.asyncio
async def test_o_nome_do_fornecedor_e_o_que_a_pessoa_ve_no_botao(monkeypatch):
    """Dizer "entra com single sign-on" a quem tem um botão da Microsoft não
    ajuda ninguém."""
    assert UserService._sso_provider_label({"azure": True}) == "Microsoft"
    assert UserService._sso_provider_label({"okta": True}) == "Okta"
    assert UserService._sso_provider_label({"google": True, "azure": True}) == "Google"
    assert UserService._sso_provider_label({}) == "single sign-on"


@pytest.mark.asyncio
async def test_email_falhado_nao_impede_o_acesso(monkeypatch):
    """O acesso é a conta existir, não o email chegar.

    Se o envio falhar, a pessoa continua provisionada e o administrador pode
    dizer-lhe por outro meio. Rebentar aqui deixaria a conta criada e a
    chamada com erro — o pior dos dois mundos.
    """
    svc = _service({"password": False, "google": True})
    _tenant(monkeypatch)
    data = MagicMock(email="nova@cliente.com", name="Nova", avatar=None, role="member")

    with (
        patch("src.services.user_service.check_permission", return_value=True),
        patch("src.services.user_service.ensure_default_page_and_space", AsyncMock()),
        patch("src.services.user_service.EmailService") as email_cls,
        patch("src.services.user_service.user_to_response_dict", lambda u: {}),
        patch("src.schemas.user.UserResponse.model_validate", lambda d: d),
    ):
        email_cls.return_value.send_sso_access_email.side_effect = RuntimeError("SMTP down")
        await svc.create_user(data, _Caller())

    svc.user_repo.create.assert_awaited()
