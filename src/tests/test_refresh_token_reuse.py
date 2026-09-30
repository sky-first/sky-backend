"""BE-05 · Refresh-token rotation with reuse detection — T-05.1…T-05.6.

Rotation already existed; what this suite locks in is the *family* behaviour:
replaying a token that was already rotated (theft) revokes the whole login
lineage, while unrelated logins stay untouched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnauthorizedError
from src.core.security import create_refresh_token
from src.models.user import RefreshToken
from src.services.auth_service import AuthenticationService


async def _store_login_token(
    db: AsyncSession,
    user,
    *,
    family_id=None,
    expires_delta: timedelta = timedelta(days=7),
):
    """Persist a refresh token as if a fresh login had just minted it."""
    token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
    raw = create_refresh_token(token_data)
    row = RefreshToken(
        user_id=user.id,
        token=raw,
        expires_at=datetime.now(timezone.utc) + expires_delta,
        family_id=family_id or uuid4(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return raw, row


async def _row(db: AsyncSession, token: str) -> RefreshToken:
    result = await db.execute(select(RefreshToken).where(RefreshToken.token == token))
    return result.scalar_one_or_none()


async def _envelhecer_rotacao(db: AsyncSession, token: str) -> None:
    """Empurra a rotacao para tras da `JANELA_DE_GRACA`.

    BE-09 — a partir de 30/09 um token acabado de rodar e devolvido com o
    mesmo filho, em vez de disparar o alarme: quatro renovacoes em paralelo
    (que e o que a app faz ao voltar do segundo plano) deixaram de matar a
    familia. Os testes de ROUBO tem de sair dessa janela, senao passam a
    exercitar o caminho da corrida e nao o do atacante.
    """
    row = await _row(db, token)
    row.revoked_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db.commit()


@pytest.mark.asyncio
class TestRefreshReuse:
    # ─── T-05.1 · happy rotation stays in the same family ────────────────────
    async def test_t05_1_rotation_keeps_family(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw, row = await _store_login_token(db_session, test_user["user"])
        family = row.family_id

        resp = await svc.refresh_access_token(raw)

        assert resp.access_token and resp.refresh_token != raw
        old = await _row(db_session, raw)
        new = await _row(db_session, resp.refresh_token)
        assert old.revoked_at is not None  # parent rotated out
        assert new.revoked_at is None
        assert new.family_id == family  # child inherits the lineage

    # ─── T-05.2 · replaying a rotated token nukes the whole family ───────────
    async def test_t05_2_reuse_revokes_family(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])

        resp = await svc.refresh_access_token(raw_a)  # A → B (A now revoked)
        raw_b = resp.refresh_token

        # 🚨 Replay A (the already-rotated token), fora da janela de graca.
        await _envelhecer_rotacao(db_session, raw_a)
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(raw_a)
        assert "reuse" in str(exc.value).lower()

        # The still-live child B must now be revoked too — the family is dead.
        assert (await _row(db_session, raw_b)).revoked_at is not None

    # ─── T-05.3 · after reuse, even the newest token can't refresh ───────────
    async def test_t05_3_family_dead_newest_token_fails(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])
        raw_b = (await svc.refresh_access_token(raw_a)).refresh_token

        await _envelhecer_rotacao(db_session, raw_a)
        with pytest.raises(UnauthorizedError):
            await svc.refresh_access_token(raw_a)  # trip the reuse detector

        # B was revoked by the nuke → replaying it is itself reuse, not a 401.
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(raw_b)
        assert "reuse" in str(exc.value).lower()

    # ─── T-05.4 · an unrelated login family is untouched ─────────────────────
    async def test_t05_4_other_family_survives(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        user = test_user["user"]
        raw_a, _ = await _store_login_token(db_session, user)  # family 1
        raw_c, row_c = await _store_login_token(db_session, user)  # family 2
        assert row_c.family_id is not None

        await svc.refresh_access_token(raw_a)  # rotate family 1
        await _envelhecer_rotacao(db_session, raw_a)
        with pytest.raises(UnauthorizedError):
            await svc.refresh_access_token(raw_a)  # nuke family 1

        # Family 2 never touched → still rotates cleanly.
        resp = await svc.refresh_access_token(raw_c)
        assert resp.refresh_token and resp.refresh_token != raw_c

    # ─── T-05.5 · a token we never issued → plain 401, no nuke ───────────────
    async def test_t05_5_unknown_token_is_invalid(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        user = test_user["user"]
        live_raw, _ = await _store_login_token(db_session, user)

        # Valid signature, but never persisted.
        ghost = create_refresh_token({"sub": str(user.id), "email": user.email, "role": user.role})
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(ghost)
        assert "invalid" in str(exc.value).lower()

        # Nothing was nuked — the genuine live token still works.
        assert (await _row(db_session, live_raw)).revoked_at is None

    # ─── T-05.6 · an expired (but valid-signature) token → 401 ───────────────
    async def test_t05_6_expired_token(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw, _ = await _store_login_token(
            db_session, test_user["user"], expires_delta=timedelta(days=-1)
        )
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(raw)
        assert "expired" in str(exc.value).lower()

    # ─── T-05.7 · the REAL issuance path opens a family ──────────────────────
    async def test_t05_7_real_login_opens_a_family(self, db_session, test_user):
        # The whole scheme rests on a real login opening a family. Exercise the
        # shared issuance path (login / MFA / SSO / select-workspace all funnel
        # through _issue_session) instead of the injected helper, so a broken
        # stamp is actually caught here.
        svc = AuthenticationService(db_session)
        resp = await svc._issue_session(test_user["user"])
        row = await _row(db_session, resp.refresh_token)
        assert row is not None
        assert row.family_id is not None  # login lineage was stamped

    # ─── T-05.8 · reuse also bumps the access-token blocklist (Option A) ─────
    async def test_t05_8_reuse_bumps_access_blocklist(self, db_session, test_user, monkeypatch):
        # Redis is absent under test, so the real revoke_user_tokens is a no-op.
        # Spy on it to prove Option A actually fires with the right arguments.
        import src.core.token_blocklist as bl

        calls = []

        async def _spy(user_id, *, issued_before_epoch):
            calls.append((user_id, issued_before_epoch))

        monkeypatch.setattr(bl, "revoke_user_tokens", _spy)

        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])
        await svc.refresh_access_token(raw_a)  # rotate A → B
        await _envelhecer_rotacao(db_session, raw_a)
        with pytest.raises(UnauthorizedError):
            await svc.refresh_access_token(raw_a)  # reuse → must bump blocklist

        assert len(calls) == 1
        assert calls[0][0] == str(test_user["user"].id)
        assert isinstance(calls[0][1], int)  # epoch second


@pytest.mark.asyncio
class TestJanelaDeGraca:
    """BE-09 — renovacoes simultaneas deixaram de matar a sessao.

    ⚠️ **O que isto corrige, com a prova.**

    Quando a app volta do segundo plano, varios ecras pedem ao mesmo tempo:
    presenca, conversas, websocket, voz. Todos apanham 401, todos renovam,
    todos com o MESMO refresh token.

    O primeiro rodava e revogava o antigo; os outros chegavam com o token ja
    revogado, caiam no detector de reutilizacao, e esse revogava a FAMILIA
    INTEIRA — incluindo o token que o primeiro tinha acabado de emitir. A
    sessao morria depois de renovada com sucesso.

    Nos registos do ingress, 28/09/2026 as 18:22:15: quatro `/auth/refresh`,
    quatro 401. O Lucas ficou quinze horas fora da app.

    A janela de graca devolve a quem chega atrasado **o mesmo filho**. Fora
    dela, o alarme de roubo mantem-se — e e a classe `TestRefreshReuse` acima
    que o garante.
    """

    async def test_quem_chega_atrasado_recebe_o_mesmo_filho(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])

        primeiro = await svc.refresh_access_token(raw_a)   # A → B
        segundo = await svc.refresh_access_token(raw_a)    # o atrasado

        # Mesmo filho — nao uma segunda linhagem viva da mesma sessao.
        assert segundo.refresh_token == primeiro.refresh_token
        # Mas um access token proprio, acabado de emitir.
        assert segundo.access_token

    async def test_a_familia_sobrevive_a_corrida(self, db_session, test_user):
        """O coracao do defeito: o token do vencedor ficava revogado."""
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])

        raw_b = (await svc.refresh_access_token(raw_a)).refresh_token
        await svc.refresh_access_token(raw_a)  # o atrasado

        assert (await _row(db_session, raw_b)).revoked_at is None, (
            "o filho do vencedor foi revogado pela corrida — e o defeito de 28/09"
        )

    async def test_quatro_ao_mesmo_tempo_continuam_a_poder_renovar(
        self, db_session, test_user
    ):
        """Os quatro pedidos do caso real, e a sessao continua viva."""
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])

        respostas = [await svc.refresh_access_token(raw_a) for _ in range(4)]

        # Todos servidos, todos com o mesmo filho.
        assert len({r.refresh_token for r in respostas}) == 1
        # E esse filho continua a servir para renovar a seguir.
        seguinte = await svc.refresh_access_token(respostas[0].refresh_token)
        assert seguinte.refresh_token != respostas[0].refresh_token

    async def test_fora_da_janela_continua_a_ser_roubo(self, db_session, test_user):
        """⚠️ A fresta e estreita de proposito — esta e a prova."""
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])
        raw_b = (await svc.refresh_access_token(raw_a)).refresh_token

        await _envelhecer_rotacao(db_session, raw_a)

        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(raw_a)
        assert "reuse" in str(exc.value).lower()
        assert (await _row(db_session, raw_b)).revoked_at is not None

    async def test_a_janela_e_curta(self):
        """Dez segundos. Se alguem a alargar, que seja com dados.

        A janela conta-se a partir da rotacao e nao se renova. Quanto maior,
        maior a fresta para um token roubado ser trocado pelo mesmo filho em
        vez de disparar o alarme.
        """
        assert AuthenticationService.JANELA_DE_GRACA <= timedelta(seconds=30)

    async def test_familia_ja_morta_nao_ressuscita(self, db_session, test_user):
        """Depois de um roubo detectado, a janela nao serve de porta lateral.

        Se a familia foi revogada, nao ha filho vivo — e o alarme tem de
        continuar a disparar mesmo para um token rodado ha um segundo.
        """
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])
        raw_b = (await svc.refresh_access_token(raw_a)).refresh_token

        await _envelhecer_rotacao(db_session, raw_a)
        with pytest.raises(UnauthorizedError):
            await svc.refresh_access_token(raw_a)  # mata a familia

        # Agora o B, revogado pela limpeza, ha pouco tempo.
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(raw_b)
        assert "reuse" in str(exc.value).lower()
