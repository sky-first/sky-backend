"""RGPD (decisões de 15/10/2026): remoção → sessões mortas já, anonimização
aos 30 dias; retenção de 12 meses da auditoria.

Testes de COMPORTAMENTO: cada um diz o que a política de privacidade promete
e verifica-o na base, não na implementação.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from src.core.exceptions import BadRequestError
from src.core.security import create_access_token, create_refresh_token
from src.models.audit import AuditEvent
from src.models.device import Device
from src.models.internal_console import InternalConsoleAudit
from src.models.notification import Notification
from src.models.user import RefreshToken, User
from src.services.audit_service import AuditService
from src.services.rgpd_service import (
    NOME_ANONIMO,
    aplicar_retencao,
    anonimizar_removidos,
)
from src.services.user_service import UserService

AGORA = datetime.now(timezone.utc)


def _user(role: str = "member", **kw) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@cliente-exemplo.pt",
        name="Maria Exemplo",
        password_hash="x",
        role=role,
        **kw,
    )


async def _com_sessao_e_aparelho(db, user: User) -> dict:
    dados = {"sub": str(user.id), "email": user.email, "role": user.role}
    access = create_access_token(dados)
    refresh = create_refresh_token(dados)
    db.add(
        RefreshToken(
            user_id=user.id,
            token=refresh,
            expires_at=AGORA + timedelta(days=7),
            ip_address="203.0.113.7",
            user_agent="Mozilla/5.0 (iPhone)",
        )
    )
    db.add(
        Device(
            user_id=user.id,
            platform="ios",
            push_token=f"ExponentPushToken[{uuid.uuid4().hex}]",
            provider="expo",
        )
    )
    await db.commit()
    return {"access": access, "refresh": refresh}


async def _conta(db, modelo, *cond) -> int:
    return (await db.execute(select(func.count()).select_from(modelo).where(*cond))).scalar()


# ── A) No momento da remoção ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remocao_revoga_sessoes_e_apaga_aparelhos(db_session):
    admin, alvo, outro = _user("admin"), _user(), _user()
    db_session.add_all([admin, alvo, outro])
    await db_session.commit()
    await _com_sessao_e_aparelho(db_session, alvo)
    await _com_sessao_e_aparelho(db_session, outro)

    await UserService(db_session).delete_user(user_id=alvo.id, current_user=admin)

    assert await _conta(db_session, Device, Device.user_id == alvo.id) == 0
    assert (
        await _conta(
            db_session,
            RefreshToken,
            RefreshToken.user_id == alvo.id,
            RefreshToken.revoked_at.is_(None),
        )
        == 0
    )
    # Quem não foi removido não perde nada.
    assert await _conta(db_session, Device, Device.user_id == outro.id) == 1
    assert (
        await _conta(
            db_session,
            RefreshToken,
            RefreshToken.user_id == outro.id,
            RefreshToken.revoked_at.is_(None),
        )
        == 1
    )


@pytest.mark.asyncio
async def test_access_token_ja_emitido_e_recusado_depois_da_remocao(async_client, db_session):
    admin, alvo = _user("admin"), _user()
    db_session.add_all([admin, alvo])
    await db_session.commit()
    tokens = await _com_sessao_e_aparelho(db_session, alvo)
    cab = {"Authorization": f"Bearer {tokens['access']}"}

    antes = await async_client.get("/api/v1/auth/me", headers=cab)
    assert antes.status_code == 200

    await UserService(db_session).delete_user(user_id=alvo.id, current_user=admin)

    depois = await async_client.get("/api/v1/auth/me", headers=cab)
    assert depois.status_code == 401
    # E o refresh token também já não serve para arranjar outro.
    r = await async_client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh"]})
    assert r.status_code == 401


# ── A) Aos 30 dias ───────────────────────────────────────────────────────


async def _removido_ha(db, dias: float, **kw) -> User:
    u = _user(**kw)
    u.deleted_at = AGORA - timedelta(days=dias)
    u.avatar = "data:image/png;base64,AAAA"
    u.auth_provider_id = "google-oauth2|123"
    u.auth0_id = f"auth0|{uuid.uuid4().hex}"
    u.sso_metadata = {"email": u.email, "name": u.name}
    u.mfa_enabled = True
    u.mfa_secret_encrypted = b"segredo"
    u.last_login_at = AGORA - timedelta(days=dias + 1)
    db.add(u)
    await db.commit()
    return u


@pytest.mark.asyncio
async def test_anonimiza_aos_30_dias_e_nao_antes(db_session):
    velho = await _removido_ha(db_session, 31)
    recente = await _removido_ha(db_session, 29)
    activo = _user()
    db_session.add(activo)
    await db_session.commit()
    email_velho, email_recente = velho.email, recente.email

    # Rasto do removido: sessão, aparelho, notificação e auditoria.
    await _com_sessao_e_aparelho(db_session, velho)
    db_session.add(
        Notification(
            user_id=velho.id,
            type="mention",
            title="Foste mencionada",
            entity_type="message",
            entity_id="x",
        )
    )
    audit = AuditService(db_session)
    for acao in ("pages.read", "connections.read"):
        await audit.log_event(
            actor_kind="user",
            actor_id=velho.id,
            actor_email=email_velho,
            action=acao,
            decision="allow",
            ip="203.0.113.7",
            user_agent="Mozilla/5.0",
        )
    await db_session.commit()

    res = await anonimizar_removidos(db_session, dias=30, dry_run=False)
    assert res.contagens["utilizadores_anonimizados"] == 1
    assert not res.falhas

    await db_session.refresh(velho)
    assert velho.name == NOME_ANONIMO
    assert velho.email.startswith("removido-") and velho.email.endswith(
        "@removido.skyfirstlabs.com"
    )
    assert email_velho not in velho.email
    assert velho.avatar is None
    assert velho.auth_provider_id is None and velho.auth0_id is None
    assert velho.sso_metadata is None
    assert velho.mfa_enabled is False and velho.mfa_secret_encrypted is None
    assert velho.last_login_at is None
    assert velho.anonymized_at is not None
    assert await _conta(db_session, RefreshToken, RefreshToken.user_id == velho.id) == 0
    assert await _conta(db_session, Device, Device.user_id == velho.id) == 0
    assert await _conta(db_session, Notification, Notification.user_id == velho.id) == 0

    # A auditoria FICA (é prova), sem email/IP/UA — e a cadeia continua válida.
    linhas = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.actor_id == velho.id)))
        .scalars()
        .all()
    )
    assert len(linhas) == 2
    assert all(e.actor_email is None and e.ip is None and e.user_agent is None for e in linhas)
    assert (await audit.verify_chain())["valid"] is True

    # Removido há 29 dias: intacto (ainda se pode restaurar).
    await db_session.refresh(recente)
    assert recente.email == email_recente and recente.name == "Maria Exemplo"
    assert recente.anonymized_at is None
    await db_session.refresh(activo)
    assert activo.anonymized_at is None


@pytest.mark.asyncio
async def test_anonimizacao_mantem_mensagens_sem_identificar_o_autor(db_session):
    from src.models.conversation import Conversation, Message

    velho = await _removido_ha(db_session, 40)
    # SQLite sem FKs: a página não precisa de existir para o que se testa.
    conv = Conversation(
        id=uuid.uuid4(), page_id=uuid.uuid4(), created_by=velho.id, title="Vendas Q3"
    )
    db_session.add(conv)
    await db_session.flush()
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role="user",
        kind="question",
        content="Quanto vendemos em Setembro?",
        user_id=velho.id,
    )
    db_session.add(msg)
    await db_session.commit()

    await anonimizar_removidos(db_session, dias=30, dry_run=False)

    await db_session.refresh(msg)
    assert msg.content == "Quanto vendemos em Setembro?"  # da organização: fica
    autor = await db_session.get(User, msg.user_id)
    assert autor.name == NOME_ANONIMO  # o nome mostrado vem daqui


@pytest.mark.asyncio
async def test_anonimizacao_e_idempotente(db_session):
    velho = await _removido_ha(db_session, 60)
    await anonimizar_removidos(db_session, dias=30, dry_run=False)
    await db_session.refresh(velho)
    email_1 = velho.email

    res = await anonimizar_removidos(db_session, dias=30, dry_run=False)
    assert res.contagens.get("utilizadores_por_anonimizar") == 0
    assert "utilizadores_anonimizados" not in res.contagens
    await db_session.refresh(velho)
    assert velho.email == email_1  # não volta a mexer


@pytest.mark.asyncio
async def test_anonimizacao_dry_run_conta_e_nao_escreve(db_session):
    velho = await _removido_ha(db_session, 45)
    email = velho.email
    await _com_sessao_e_aparelho(db_session, velho)

    res = await anonimizar_removidos(db_session, dias=30, dry_run=True)
    assert res.contagens == {"utilizadores_por_anonimizar": 1}

    await db_session.refresh(velho)
    assert velho.email == email and velho.anonymized_at is None
    assert await _conta(db_session, Device, Device.user_id == velho.id) == 1


@pytest.mark.asyncio
async def test_anonimizacao_nunca_toca_em_operadores_nem_no_sistema(db_session):
    op = await _removido_ha(db_session, 90, is_sky_operator=True)
    sis = await _removido_ha(db_session, 90, status="sistema")
    res = await anonimizar_removidos(db_session, dias=30, dry_run=False)
    assert res.contagens["utilizadores_por_anonimizar"] == 0
    for u in (op, sis):
        await db_session.refresh(u)
        assert u.anonymized_at is None


@pytest.mark.asyncio
async def test_restaurar_dentro_dos_30_dias_sim_depois_nao(db_session):
    admin = _user("admin")
    db_session.add(admin)
    await db_session.commit()
    recente = await _removido_ha(db_session, 10)
    velho = await _removido_ha(db_session, 31)
    await anonimizar_removidos(db_session, dias=30, dry_run=False)

    svc = UserService(db_session)
    await svc.restore_user(recente.id, admin)
    await db_session.refresh(recente)
    assert recente.deleted_at is None

    with pytest.raises(BadRequestError):
        await svc.restore_user(velho.id, admin)
    await db_session.refresh(velho)
    assert velho.deleted_at is not None


# ── B) Retenção ──────────────────────────────────────────────────────────


def _evento(dias: int, n: int) -> AuditEvent:
    return AuditEvent(
        occurred_at=AGORA - timedelta(days=dias),
        actor_kind="user",
        actor_id=uuid.uuid4(),
        actor_email="alguem@cliente-exemplo.pt",
        action="pages.read",
        decision="allow",
        ip="203.0.113.9",
        this_hash=f"{n:064d}",
    )


async def _semear_retencao(db) -> None:
    db.add_all([_evento(400, 1), _evento(366, 2), _evento(300, 3), _evento(1, 4)])
    for dias in (500, 10):
        db.add(
            InternalConsoleAudit(
                actor_email="ops@skyfirstlabs.com",
                action="view_tenant",
                result="success",
                timestamp=AGORA - timedelta(days=dias),
            )
        )
    u = _user()
    db.add(u)
    await db.flush()
    for expirou_ha in (40, 10, -5):  # -5 = ainda válido
        db.add(
            RefreshToken(
                user_id=u.id,
                token=uuid.uuid4().hex,
                expires_at=AGORA - timedelta(days=expirou_ha),
                ip_address="203.0.113.1",
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_retencao_apaga_mais_de_365_dias_e_nao_o_resto(db_session):
    await _semear_retencao(db_session)

    res = await aplicar_retencao(
        db_session, dias_auditoria=365, dias_sessoes_expiradas=30, dry_run=False
    )
    assert res.contagens["audit_events_apagados"] == 2
    assert res.contagens["internal_console_audit_apagados"] == 1
    assert res.contagens["refresh_tokens_expirados_apagados"] == 1
    assert not res.falhas

    assert await _conta(db_session, AuditEvent) == 2
    corte = AGORA - timedelta(days=365)
    assert await _conta(db_session, AuditEvent, AuditEvent.occurred_at < corte) == 0
    assert await _conta(db_session, InternalConsoleAudit) == 1
    assert await _conta(db_session, RefreshToken) == 2

    # Idempotente: a segunda passagem não encontra nada.
    res2 = await aplicar_retencao(
        db_session, dias_auditoria=365, dias_sessoes_expiradas=30, dry_run=False
    )
    assert res2.contagens["audit_events_apagados"] == 0
    assert res2.contagens["refresh_tokens_expirados_apagados"] == 0


@pytest.mark.asyncio
async def test_retencao_dry_run_conta_e_nao_apaga(db_session):
    await _semear_retencao(db_session)

    res = await aplicar_retencao(
        db_session, dias_auditoria=365, dias_sessoes_expiradas=30, dry_run=True
    )
    assert res.contagens["audit_events_a_apagar"] == 2
    assert res.contagens["internal_console_audit_a_apagar"] == 1
    assert res.contagens["refresh_tokens_expirados_a_apagar"] == 1
    assert await _conta(db_session, AuditEvent) == 4
    assert await _conta(db_session, InternalConsoleAudit) == 2
    assert await _conta(db_session, RefreshToken) == 3


@pytest.mark.asyncio
async def test_retencao_recusa_prazos_absurdos(db_session):
    # Um RETENCAO_AUDITORIA_DIAS=0 mal escrito apagava a auditoria toda.
    with pytest.raises(ValueError):
        await aplicar_retencao(
            db_session, dias_auditoria=0, dias_sessoes_expiradas=30, dry_run=False
        )
    with pytest.raises(ValueError):
        await anonimizar_removidos(db_session, dias=0, dry_run=False)


# ── A tarefa diária ──────────────────────────────────────────────────────


def test_tarefa_esta_no_beat():
    from src.workers.celery_app import celery_app

    entrada = celery_app.conf.beat_schedule["rgpd-manutencao-diaria"]
    assert entrada["task"] == "src.workers.rgpd_worker.manutencao_rgpd_diaria"
    import src.workers.rgpd_worker  # noqa: F401 — a tarefa regista-se

    assert "src.workers.rgpd_worker.manutencao_rgpd_diaria" in celery_app.tasks


@pytest.mark.asyncio
async def test_uma_base_junta_backend_e_sky_ai_e_desconfia_da_base_errada(db_session, monkeypatch):
    from src.ai import http_client
    from src.config import tenant_connection_manager as tcm
    from src.workers import rgpd_worker

    await _removido_ha(db_session, 31)
    await _semear_retencao(db_session)

    @asynccontextmanager
    async def _sessao(_ctx):
        yield db_session

    monkeypatch.setattr(tcm.tenant_connection_manager, "session_for", _sessao)

    pedidos = []

    async def _ai(self, *, dry_run, tenant_slug):
        pedidos.append((dry_run, tenant_slug))
        return {"base": tenant_slug, "contagens": {"query_audit_log_a_apagar": 7}, "falhas": []}

    monkeypatch.setattr(http_client.AIServiceHTTPClient, "aplicar_retencao_auditoria", _ai)

    r = await rgpd_worker._uma_base("sandbox", dry_run=True)
    assert pedidos == [(True, "sandbox")]
    assert r["utilizadores_por_anonimizar"] == 1
    assert r["audit_events_a_apagar"] == 2
    assert r["ai_query_audit_log_a_apagar"] == 7
    assert r["falhas"] == []
    # Dry-run: nada mudou.
    assert await _conta(db_session, AuditEvent) == 4

    # O sky-ai respondeu de OUTRA base (slug que caiu na plataforma):
    # as contagens não são deste cliente e ficam de fora.
    async def _ai_errado(self, *, dry_run, tenant_slug):
        return {"base": "default", "contagens": {"query_audit_log_a_apagar": 99}}

    monkeypatch.setattr(http_client.AIServiceHTTPClient, "aplicar_retencao_auditoria", _ai_errado)
    r = await rgpd_worker._uma_base("sandbox", dry_run=True)
    assert "ai_query_audit_log_a_apagar" not in r
    assert "sky_ai:base_errada" in r["falhas"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug,cabecalho", [("sandbox", "sandbox"), ("default", None), (None, None)]
)
async def test_cliente_do_sky_ai_manda_o_cliente_explicito_e_nunca_os_dias(
    monkeypatch, slug, cabecalho
):
    import httpx

    from src.ai import http_client

    vistos = []

    def _responder(pedido: httpx.Request) -> httpx.Response:
        vistos.append(pedido)
        return httpx.Response(200, json={"base": slug or "default", "contagens": {}})

    real = httpx.AsyncClient

    def _cliente(*a, **kw):
        kw["transport"] = httpx.MockTransport(_responder)
        return real(*a, **kw)

    monkeypatch.setattr(http_client.httpx, "AsyncClient", _cliente)
    await http_client.AIServiceHTTPClient("http://sky-ai").aplicar_retencao_auditoria(
        dry_run=True, tenant_slug=slug
    )
    (p,) = vistos
    assert p.url.path == "/privacidade/retencao"
    assert p.headers.get("x-tenant-slug") == cabecalho
    assert dict(p.url.params) == {"dry_run": "true"}  # os dias vêm do sky-ai
