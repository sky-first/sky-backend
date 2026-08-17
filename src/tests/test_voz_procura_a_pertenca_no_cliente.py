"""A voz procurava a pertença na base errada.

O portão de dispositivo existe em dois sítios e tem de dar a mesma resposta nos
dois: no REST (`deps.enforce_device_tenant`) e no WebSocket da voz
(`voice._resolve_voice_tenant`). O REST lê com a sessão do pedido — a do
**cliente** — e o login escreve com a mesma. A voz lia na base da **plataforma**,
com um comentário a afirmar que era lá que as linhas viviam.

Não era. E o defeito só apareceu no dia em que a pertença passou a existir: o
`/auth/me` passou a responder 200 e a voz continuou a recusar, com
"Servidor de voz indisponível" no microfone e no live talk. Duas verificações
que são a mesma, a olhar para gavetas diferentes.

Este teste não verifica a mensagem de erro nem o áudio: verifica **em que base
de dados** a pergunta é feita. É aí que estava a mentira.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


def _ctx(tenant_id, slug="skyfirstlabs"):
    return SimpleNamespace(id=tenant_id, slug=slug, is_default=False)


@pytest.mark.asyncio
async def test_a_pertenca_e_procurada_na_base_do_cliente():
    from src.api.v1 import voice

    tid = uuid4()
    ctx_cliente = _ctx(tid)
    bases_consultadas = []

    class _Sessao:
        async def __aenter__(self):
            return "sessao"

        async def __aexit__(self, *a):
            return False

    def _session_for(ctx):
        bases_consultadas.append(getattr(ctx, "slug", "plataforma"))
        return _Sessao()

    with patch(
        "src.config.settings.settings.MULTI_TENANT_ENABLED", True
    ), patch(
        "src.api.middleware.tenant_resolver._load_tenant_by_id",
        AsyncMock(return_value=ctx_cliente),
    ), patch(
        "src.config.tenant_connection_manager.tenant_connection_manager.session_for",
        _session_for,
    ), patch(
        "src.services.tenant_membership_service.TenantMembershipService.is_member",
        AsyncMock(return_value=True),
    ):
        resultado = await voice._resolve_voice_tenant(
            {"sub": str(uuid4()), "tid": str(tid)}
        )

    assert resultado is ctx_cliente, "com pertença, a voz tem de deixar entrar"
    assert bases_consultadas, "a pertença tem de ser procurada em alguma base"
    assert "plataforma" not in bases_consultadas, (
        "a pertença vive na base do cliente — procurá-la na da plataforma é "
        "não a encontrar nunca, e recusar toda a gente"
    )


@pytest.mark.asyncio
async def test_sem_pertenca_a_voz_recusa():
    """A metade que não pode enfraquecer: quem saiu da empresa não fala."""
    from src.api.v1 import voice

    tid = uuid4()

    class _Sessao:
        async def __aenter__(self):
            return "sessao"

        async def __aexit__(self, *a):
            return False

    with patch(
        "src.config.settings.settings.MULTI_TENANT_ENABLED", True
    ), patch(
        "src.api.middleware.tenant_resolver._load_tenant_by_id",
        AsyncMock(return_value=_ctx(tid)),
    ), patch(
        "src.config.tenant_connection_manager.tenant_connection_manager.session_for",
        lambda ctx: _Sessao(),
    ), patch(
        "src.services.tenant_membership_service.TenantMembershipService.is_member",
        AsyncMock(return_value=False),
    ):
        resultado = await voice._resolve_voice_tenant(
            {"sub": str(uuid4()), "tid": str(tid)}
        )

    assert resultado is None


@pytest.mark.asyncio
async def test_cliente_que_nao_resolve_recusa():
    from src.api.v1 import voice

    with patch(
        "src.config.settings.settings.MULTI_TENANT_ENABLED", True
    ), patch(
        "src.api.middleware.tenant_resolver._load_tenant_by_id",
        AsyncMock(return_value=None),
    ):
        resultado = await voice._resolve_voice_tenant(
            {"sub": str(uuid4()), "tid": str(uuid4())}
        )

    assert resultado is None
