"""«Dar acceso» diz a verdade sobre o email.

A app lia ``access_email_sent`` e ``POST /auth/invite/generate`` só devolvia
``email_sent``: com o SES a recusar, a app dizia na mesma «enviámos-lhe um
email» (auditoria da app, 12/10/2026). A resposta leva agora os três nomes
com o mesmo valor; ``email_enviado`` é o do contrato.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import update

from src.core.security import create_access_token
from src.models.user import User


@pytest.mark.asyncio
@pytest.mark.parametrize("saiu", [True, False])
async def test_a_resposta_diz_se_o_email_saiu(
    async_client, test_user_with_tokens, db_session, saiu
):
    user = test_user_with_tokens["user"]
    await db_session.execute(update(User).where(User.id == user.id).values(role="admin"))
    await db_session.commit()
    token = create_access_token({"sub": str(user.id), "email": user.email, "role": "admin"})

    with patch(
        "src.services.invite_service.InviteService.create_invite",
        new=AsyncMock(return_value=("tok", saiu)),
    ):
        r = await async_client.post(
            "/api/v1/auth/invite/generate",
            json={"email": "nova@example.com", "name": "Nova", "role": "member"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code in (200, 201), r.text
    corpo = r.json()
    assert corpo["email_enviado"] is saiu
    assert corpo["access_email_sent"] is saiu
    assert corpo["email_sent"] is saiu
