"""Push dispatch tests (BE-06 · T-06.3/.4/.5/.6/.7/.8/.9).

The dispatcher turns a created notification into device pushes: only
*material* findings fire, they fan out to every device, tapping carries
a deep link, dead tokens get pruned, and one user's push never reaches
another user's device. A fake provider stands in for APNs/Expo so the
whole path is exercised without credentials.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification import NotificationType
from src.repositories.device_repository import DeviceRepository
from src.schemas.device import DeviceRegister
from src.schemas.notification import NotificationCreate, NotificationResponse
from src.services.notification_service import NotificationService
from src.services.push_dispatcher import PushDispatcher
from src.services.push_provider import PushMessage, PushResult


class FakeProvider:
    """Records what it was asked to send; can report tokens as invalid."""

    def __init__(self, invalid: List[str] | None = None):
        self.invalid = invalid or []
        self.sent: List[PushMessage] = []

    async def send(self, messages: List[PushMessage]) -> PushResult:
        self.sent.extend(messages)
        return PushResult(sent=len(messages) - len(self.invalid), invalid_tokens=list(self.invalid))


async def _register(db: AsyncSession, user_id, token: str, platform: str = "ios"):
    return await DeviceRepository(db).upsert(
        user_id, DeviceRegister(platform=platform, push_token=token)
    )


def _notif(
    user_id, type_: str, deep_link: str | None = "/dashboard?insight=w1"
) -> NotificationResponse:
    return NotificationResponse(
        id=uuid.uuid4(),
        user_id=user_id,
        type=type_,
        title="Material change",
        description="Revenue up 30%",
        entity_type="agent_execution",
        entity_id="run-1",
        deep_link=deep_link,
        is_read=False,
        read_at=None,
        created_at=datetime.now(timezone.utc),
    )


# ─── T-06.3 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_material_finding_pushes(test_user_with_tokens: dict, db_session: AsyncSession):
    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-1")
    fake = FakeProvider()

    sent = await PushDispatcher(db_session, provider=fake).dispatch(
        _notif(user.id, NotificationType.INSIGHT_AGENT_MATERIAL.value)
    )
    assert sent == 1
    assert len(fake.sent) == 1


# ─── T-06.4 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_routine_finding_no_push(test_user_with_tokens: dict, db_session: AsyncSession):
    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-1")
    fake = FakeProvider()

    sent = await PushDispatcher(db_session, provider=fake).dispatch(
        _notif(user.id, NotificationType.INSIGHT_AGENT_RESULT.value)  # routine
    )
    assert sent == 0
    assert fake.sent == []


# ─── T-06.5 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_muted_user_no_push(
    test_user_with_tokens: dict, db_session: AsyncSession, monkeypatch
):
    """Focus mode / mute is enforced upstream: a muted notification never
    gets written, so it never reaches the dispatcher."""
    from src.models.notification import NotificationPreference

    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-1")
    # Global focus mode — pause everything.
    db_session.add(
        NotificationPreference(
            user_id=user.id,
            scope_type="global",
            scope_value=None,
            channel="all",
            enabled=False,
        )
    )
    await db_session.commit()

    fake = FakeProvider()
    monkeypatch.setattr("src.services.push_dispatcher.build_push_provider", lambda: fake)

    created = await NotificationService(db_session).create_notification(
        NotificationCreate(
            user_id=user.id,
            type=NotificationType.INSIGHT_AGENT_MATERIAL.value,
            title="Material change",
            entity_type="agent_execution",
            entity_id="run-1",
        )
    )
    assert created is None  # muted → not written
    assert fake.sent == []  # → not pushed


# ─── T-06.5 (companion: non-muted goes through the service wiring) ───────────
@pytest.mark.asyncio
async def test_service_dispatches_material_when_not_muted(
    test_user_with_tokens: dict, db_session: AsyncSession, monkeypatch
):
    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-1")
    fake = FakeProvider()
    monkeypatch.setattr("src.services.push_dispatcher.build_push_provider", lambda: fake)

    created = await NotificationService(db_session).create_notification(
        NotificationCreate(
            user_id=user.id,
            type=NotificationType.INSIGHT_AGENT_MATERIAL.value,
            title="Material change",
            entity_type="agent_execution",
            entity_id="run-1",
            deep_link="/dashboard?insight=w1",
        )
    )
    assert created is not None
    assert len(fake.sent) == 1


# ─── T-06.6 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_invalid_token_pruned(test_user_with_tokens: dict, db_session: AsyncSession):
    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-good")
    await _register(db_session, user.id, "tok-dead")
    fake = FakeProvider(invalid=["tok-dead"])

    await PushDispatcher(db_session, provider=fake).dispatch(
        _notif(user.id, NotificationType.INSIGHT_AGENT_MATERIAL.value)
    )
    remaining = {d.push_token for d in await DeviceRepository(db_session).list_for_user(user.id)}
    assert remaining == {"tok-good"}  # dead token pruned, no repeated failures


# ─── T-06.7 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_fan_out_to_all_devices(test_user_with_tokens: dict, db_session: AsyncSession):
    user = test_user_with_tokens["user"]
    for i in range(3):
        await _register(db_session, user.id, f"tok-{i}")
    fake = FakeProvider()

    sent = await PushDispatcher(db_session, provider=fake).dispatch(
        _notif(user.id, NotificationType.INSIGHT_AGENT_MATERIAL.value)
    )
    assert sent == 3
    assert len(fake.sent) == 3


# ─── T-06.8 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cross_user_isolation(
    test_user_with_tokens: dict,
    test_second_user_with_tokens: dict,
    db_session: AsyncSession,
):
    """A notification for user B must never reach user A's device."""
    user_a = test_user_with_tokens["user"]
    user_b_id = uuid.UUID(test_second_user_with_tokens["user"]["id"])
    await _register(db_session, user_a.id, "tok-a")
    fake = FakeProvider()

    sent = await PushDispatcher(db_session, provider=fake).dispatch(
        _notif(user_b_id, NotificationType.INSIGHT_AGENT_MATERIAL.value)
    )
    assert sent == 0
    assert fake.sent == []  # user A's token never targeted
    # And user A still owns their device.
    assert len(await DeviceRepository(db_session).list_for_user(user_a.id)) == 1


# ─── T-06.9 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_push_carries_deep_link(test_user_with_tokens: dict, db_session: AsyncSession):
    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-1")
    fake = FakeProvider()

    await PushDispatcher(db_session, provider=fake).dispatch(
        _notif(
            user.id,
            NotificationType.INSIGHT_AGENT_MATERIAL.value,
            deep_link="/dashboard?insight=w9",
        )
    )
    assert fake.sent[0].data["deep_link"] == "/dashboard?insight=w9"
    assert fake.sent[0].data["entity_type"] == "agent_execution"
    assert fake.sent[0].data["entity_id"] == "run-1"


# ─── Menções, convites e o `data` que a app sabe abrir ──────────────────────
#
# Só os achados geravam push, e o do achado levava `entity_type="agent"` mais
# um link da web: tocar não abria nada. Ver o contrato em push_dispatcher.py.


@pytest.mark.asyncio
async def test_mencao_gera_push_que_abre_a_conversa(
    test_user_with_tokens: dict, db_session: AsyncSession, monkeypatch
):
    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-1")
    fake = FakeProvider()
    monkeypatch.setattr("src.services.push_dispatcher.build_push_provider", lambda: fake)
    conv = str(uuid.uuid4())

    await NotificationService(db_session).create_notification(
        NotificationCreate(
            user_id=user.id,
            type=NotificationType.COMMENT_MENTION.value,
            title="Foi mencionado num comentário",
            entity_type="conversation",
            entity_id=conv,
            deep_link=f"/page?id=p&conversation={conv}",
        )
    )
    assert len(fake.sent) == 1
    data = fake.sent[0].data
    assert data["target"] == "conversation"
    assert data["conversation_id"] == conv
    assert data["entity_type"] == "conversation"
    assert data["type"] == "comment_mention"
    assert fake.sent[0].title == "Foi mencionado num comentário"


@pytest.mark.asyncio
async def test_convite_gera_push_e_a_recusa_nao(
    test_user_with_tokens: dict, db_session: AsyncSession, monkeypatch
):
    from sqlalchemy import update

    from src.models.user import User

    user = test_user_with_tokens["user"]
    await db_session.execute(
        update(User).where(User.id == user.id).values(preferences={"language": "es"})
    )
    await db_session.commit()
    await _register(db_session, user.id, "tok-1")
    fake = FakeProvider()
    monkeypatch.setattr("src.services.push_dispatcher.build_push_provider", lambda: fake)
    space = str(uuid.uuid4())
    svc = NotificationService(db_session)

    await svc.create_notification(
        NotificationCreate(
            user_id=user.id,
            type="space_invite",
            title="notif.projectInvite",
            title_key="notif.projectInvite",
            title_params={"person": "Ana", "project": "Ventas"},
            entity_type="space",
            entity_id=space,
        )
    )
    assert len(fake.sent) == 1
    # O título vem montado na língua da pessoa — e não a chave crua.
    assert fake.sent[0].title == "Ana le ha invitado a «Ventas»"
    assert fake.sent[0].data["target"] == "notifications"
    assert fake.sent[0].data["space_id"] == space

    await svc.create_notification(
        NotificationCreate(
            user_id=user.id,
            type="space_invite",
            title="notif.projectInviteDeclined",
            title_key="notif.projectInviteDeclined",
            entity_type="space",
            entity_id=space,
        )
    )
    assert len(fake.sent) == 1  # a recusa fica só na app


@pytest.mark.asyncio
async def test_achado_leva_ids_que_a_app_abre(
    test_user_with_tokens: dict, db_session: AsyncSession, monkeypatch
):
    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-1")
    fake = FakeProvider()
    monkeypatch.setattr("src.services.push_dispatcher.build_push_provider", lambda: fake)
    agent_id, finding_id, conv_id = (str(uuid.uuid4()) for _ in range(3))

    created = await NotificationService(db_session).create_notification(
        NotificationCreate(
            user_id=user.id,
            type="agent_finding",
            title="notif_agent_findings_title",
            title_key="notif_agent_findings_title",
            title_params={"agent": "Margens", "count": 1},
            entity_type="agent",
            entity_id=agent_id,
            deep_link=f"/dashboard/universe-intelligence?agent={agent_id}",
            push_data={
                "entity_type": "agent_finding",
                "entity_id": finding_id,
                "finding_id": finding_id,
                "agent_id": agent_id,
                "conversation_id": conv_id,
                "deep_link": f"sky://insights/{finding_id}",
            },
        )
    )
    # A linha gravada continua a apontar o agente (o «silenciar este agente»
    # depende disso); só o push muda.
    assert created.entity_type == "agent"
    assert created.entity_id == agent_id
    data = fake.sent[0].data
    assert data == {
        "type": "agent_finding",
        "notification_id": str(created.id),
        "entity_type": "agent_finding",
        "entity_id": finding_id,
        "finding_id": finding_id,
        "agent_id": agent_id,
        "conversation_id": conv_id,
        "deep_link": f"sky://insights/{finding_id}",
        "target": "insight",
    }
    assert fake.sent[0].title == "Margens: novidades nos seus dados"


@pytest.mark.asyncio
async def test_push_silenciado_so_no_canal_push(
    test_user_with_tokens: dict, db_session: AsyncSession, monkeypatch
):
    """Desligar o canal push mantém o aviso na app mas não interrompe."""
    from src.models.notification import NotificationPreference

    user = test_user_with_tokens["user"]
    await _register(db_session, user.id, "tok-1")
    db_session.add(
        NotificationPreference(
            user_id=user.id,
            scope_type="category",
            scope_value="mentions",
            channel="push",
            enabled=False,
        )
    )
    await db_session.commit()
    fake = FakeProvider()
    monkeypatch.setattr("src.services.push_dispatcher.build_push_provider", lambda: fake)

    created = await NotificationService(db_session).create_notification(
        NotificationCreate(
            user_id=user.id,
            type=NotificationType.COMMENT_MENTION.value,
            title="x",
            entity_type="conversation",
            entity_id=str(uuid.uuid4()),
        )
    )
    assert created is not None
    assert fake.sent == []


@pytest.mark.asyncio
async def test_expo_manda_token_de_acesso_e_parte_em_lotes(monkeypatch):
    import httpx

    from src.services.push_provider import ExpoPushProvider

    pedidos = []

    class _Resp:
        def __init__(self, n):
            self._n = n

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"status": "ok"}] * self._n}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            pedidos.append((json, headers))
            return _Resp(len(json))

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    msgs = [PushMessage(token=f"ExponentPushToken[{i}]", title="t") for i in range(150)]
    res = await ExpoPushProvider(access_token="segredo").send(msgs)
    assert res.sent == 150
    assert [len(p[0]) for p in pedidos] == [100, 50]
    assert pedidos[0][1]["Authorization"] == "Bearer segredo"
    assert pedidos[0][0][0]["sound"] == "default"

    pedidos.clear()
    await ExpoPushProvider(access_token="").send(msgs[:1])
    assert "Authorization" not in pedidos[0][1]


def test_push_provider_expo_por_variavel(monkeypatch):
    from src.services.push_provider import ExpoPushProvider, build_push_provider

    monkeypatch.setenv("PUSH_PROVIDER", "expo")
    monkeypatch.setenv("EXPO_ACCESS_TOKEN", "abc")
    p = build_push_provider()
    assert isinstance(p, ExpoPushProvider)
    assert p.access_token == "abc"
