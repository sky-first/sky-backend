"""Os dois passos finais do SSO da app, que só falham depois de a pessoa entrar.

Estes dois defeitos têm a mesma forma e são os piores de encontrar: a
autenticação **corre bem até ao fim** — a Google devolve, o utilizador é
encontrado, a sessão é criada — e é o passo seguinte que morre. Quem testa vê
"entrei" e só depois percebe que não entrou em lado nenhum.

1. O ``login_response`` traz um ``UserResponse`` (modelo Pydantic) lá dentro, e
   o handoff guarda-o como JSON no Redis. Rebentava com

       TypeError: Object of type UserResponse is not JSON serializable

   apanhado pelo ``except`` largo do ``issue`` e devolvido à app como
   INTERNAL_ERROR — com a pessoa já autenticada na Google.

2. O token emitido no SSO não levava o cliente. O login por password leva-o
   (``auth_service.py``), o do SSO não. A app **não manda** ``X-Tenant-Slug``:
   depois de entrar é o token que carrega o cliente. Sem o ``tid``, entra-se e
   o pedido seguinte morre com "Tenant unresolved".
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
import pytest
from fastapi.encoders import jsonable_encoder

from src.config.settings import settings
from src.core.tenant_context import TenantContext, reset_current_tenant, set_current_tenant
from src.schemas.user import LoginResponse, UserResponse
from src.services.auth0_service import Auth0Service


def _resposta_de_login():
    """O formato que o `create_login_response` devolve — com o modelo dentro."""
    utilizador = UserResponse.model_validate(
        {
            "id": uuid4(),
            "email": "lucas.ventura@skyfirstlabs.com",
            "name": "Lucas Ventura",
            "role": "admin",
            "email_verified": True,
            "has_completed_onboarding": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    )
    return {
        "access_token": "a",
        "refresh_token": "r",
        "expires_in": 3600,
        "user": utilizador,
    }


# ── 1. a serialização ───────────────────────────────────────────────────────

def test_o_payload_cru_nao_e_serializavel():
    """O defeito, fixado: sem tratamento, isto rebenta."""
    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps({"login": _resposta_de_login(), "tenant": "skyfirstlabs"})


def test_a_sessao_sobrevive_a_ida_e_volta_pelo_handoff():
    """E do outro lado reconstrói-se como sessão a sério, não como dicionário."""
    guardado = jsonable_encoder({"login": _resposta_de_login(), "tenant": "skyfirstlabs"})

    # Exactamente o que o Redis faz no meio.
    lido = json.loads(json.dumps(guardado, separators=(",", ":")))

    assert lido["tenant"] == "skyfirstlabs"
    sessao = LoginResponse(**lido["login"])  # é isto que o /sso/handoff faz
    assert sessao.access_token == "a"
    assert sessao.user.email == "lucas.ventura@skyfirstlabs.com"


# ── 2. o cliente vai assinado no token ──────────────────────────────────────

@pytest.mark.asyncio
async def test_o_token_do_sso_leva_o_cliente():
    ctx = TenantContext(
        slug="skyfirstlabs",
        id=uuid4(),
        tier="standard",
        display_name="SkyFirst Labs",
    )
    token_ctx = set_current_tenant(ctx)
    try:
        db = AsyncMock()
        db.add = lambda _obj: None
        servico = Auth0Service(db)
        utilizador = SimpleNamespace(
            id=uuid4(),
            email="lucas.ventura@skyfirstlabs.com",
            role="admin",
            last_login_at=None,
        )

        with patch(
            "src.services.auth_service.user_to_response_dict",
            return_value={
                "id": utilizador.id,
                "email": utilizador.email,
                "name": "Lucas Ventura",
                "role": "admin",
                "email_verified": True,
                "has_completed_onboarding": True,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ):
            resposta = await servico.create_login_response(utilizador)

        claims = jwt.decode(
            resposta["access_token"],
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        assert claims.get("tid"), (
            "o token do SSO tem de levar o cliente: a app não manda "
            "X-Tenant-Slug e sem o `tid` o pedido seguinte é recusado"
        )
        assert claims["sub"] == str(utilizador.id)
    finally:
        reset_current_tenant(token_ctx)
