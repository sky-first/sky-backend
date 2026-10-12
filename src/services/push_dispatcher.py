"""Push dispatcher (BE-06) — turns a created notification into device pushes.

Wired into ``NotificationService.create_notification``: once a row is
written (which already means the user hasn't muted it in-app — mute/focus is
enforced upstream, T-06.5), this decides whether the notification is
*material* enough to interrupt a phone, re-checks the **push** channel
preference, fans it out to every device the user owns (T-06.7), and prunes
tokens the provider rejects (T-06.6).

── O contrato do `data` do push (o que a app lê ao tocar) ─────────────────

Todas as chaves são strings. As três primeiras existem sempre:

  type             o tipo da notificação (``agent_finding``, ``comment_mention``…)
  notification_id  a linha em ``/notifications`` (para a marcar como lida)
  target           para onde a app deve abrir:
                     ``insight``       → ``finding_id`` (ecrã do achado)
                     ``conversation``  → ``conversation_id`` (o fio)
                     ``notifications`` → a lista de avisos (p.ex. convites)
  entity_type /    compatíveis com o ``parseDeepLink`` actual da app:
  entity_id          achado  → ``agent_finding`` + id do achado
                     menção  → ``conversation`` + id da conversa
                     convite → ``space`` + id do projeto
  deep_link        opcional; para achados é ``sky://insights/<finding_id>``
  finding_id, agent_id, conversation_id, space_id   quando se aplicam

Ver ``docs/contrato-app-auditoria-2026-10.md``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.device_repository import DeviceRepository
from src.schemas.notification import NotificationResponse
from src.services.push_provider import PushMessage, PushProvider, build_push_provider

logger = logging.getLogger(__name__)

# Só o que justifica interromper um telemóvel (masterplan §6.2 / T-06.3).
# Routine run notifications (insight_agent_result, agent_cycle_no_findings)
# deliberately stay in-app only (T-06.4). Respostas numa conversa
# (`conversation_reply`) também ficam só na app: são o «burburinho».
PUSH_ELIGIBLE_TYPES = {
    "insight_agent_material",
    "agent_finding",
    # Alguém chamou esta pessoa pelo nome.
    "comment_mention",
    "mention",
    # Um convite para um projeto (só o convite — a recusa não interrompe).
    "space_invite",
    "invite_received",
}

#: Dentro de `space_invite`, só estes títulos geram push.
_CONVITES_QUE_INTERROMPEM = {"notif.projectInvite", None, ""}

# Títulos dos pushes cuja notificação só traz a CHAVE (o `title` gravado é a
# própria chave, para a web/app traduzirem). O push é desenhado pelo sistema
# operativo, que não tem dicionário — por isso a frase monta-se aqui, na
# língua de quem recebe. Só as chaves que podem gerar push.
_TITULOS: Dict[str, Dict[str, str]] = {
    "notif_agent_findings_title": {
        "pt": "{agent}: novidades nos seus dados",
        "en": "{agent}: something changed in your data",
        "es": "{agent}: novedades en sus datos",
    },
    "notif.projectInvite": {
        "pt": "{person} convidou-o para «{project}»",
        "en": "{person} invited you to “{project}”",
        "es": "{person} le ha invitado a «{project}»",
    },
}


def _titulo(notif: NotificationResponse, locale: Optional[str]) -> str:
    """O título que o telemóvel mostra.

    Ordem: frase do servidor para a chave → o `title` gravado se não for a
    própria chave → o título genérico.
    """
    from src.core.locale import normalize_locale

    lingua = normalize_locale(locale)
    chave = (notif.title_key or "").strip()
    modelo = _TITULOS.get(chave)
    if modelo:
        try:
            return (modelo.get(lingua) or modelo["pt"]).format(**(notif.title_params or {}))
        except (KeyError, IndexError, ValueError):
            pass
    if notif.title and notif.title != chave:
        return notif.title
    return "Sky"


def _target(notif: NotificationResponse, extra: Dict[str, Any]) -> str:
    if extra.get("finding_id"):
        return "insight"
    if notif.entity_type == "conversation" or extra.get("conversation_id"):
        return "conversation"
    return "notifications"


def build_push_data(
    notif: NotificationResponse, extra: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """O `data` do push — ver o contrato no topo do ficheiro."""
    extra = {k: str(v) for k, v in (extra or {}).items() if v not in (None, "")}
    data: Dict[str, str] = {
        "type": str(notif.type),
        "notification_id": str(notif.id),
        "entity_type": str(notif.entity_type),
        "entity_id": str(notif.entity_id),
    }
    if notif.deep_link:
        data["deep_link"] = notif.deep_link
    if notif.entity_type == "conversation":
        data["conversation_id"] = str(notif.entity_id)
    if notif.entity_type == "space":
        data["space_id"] = str(notif.entity_id)
    data.update(extra)
    data["target"] = _target(notif, data)
    return data


class PushDispatcher:
    """Fan a push-eligible notification out to a user's registered devices."""

    def __init__(self, db: AsyncSession, provider: Optional[PushProvider] = None):
        self.db = db
        self.devices = DeviceRepository(db)
        self.provider = provider or build_push_provider()

    async def _silenciado_no_push(self, notif: NotificationResponse) -> bool:
        """A preferência do canal **push** (o in-app já foi visto a montante)."""
        try:
            from src.repositories.notification_preference_repository import (
                NotificationPreferenceRepository,
            )

            return await NotificationPreferenceRepository(self.db).is_muted(
                user_id=notif.user_id,
                notification_type=notif.type,
                entity_type=notif.entity_type,
                entity_id=notif.entity_id,
                channel="push",
            )
        except Exception as exc:  # noqa: BLE001 — na dúvida, não interromper
            logger.warning("push pref check failed for %s: %s", notif.id, exc)
            return True

    async def _lingua(self, user_id) -> Optional[str]:
        try:
            from src.models.user import User

            prefs = (
                await self.db.execute(select(User.preferences).where(User.id == user_id))
            ).scalar_one_or_none()
            return prefs.get("language") if isinstance(prefs, dict) else None
        except Exception:  # noqa: BLE001
            return None

    async def dispatch(
        self, notif: NotificationResponse, extra: Optional[Dict[str, Any]] = None
    ) -> int:
        """Send ``notif`` to every device of its user. Returns pushes sent.

        No-ops (returns 0) for non-material types, a user who muted push, or
        a user with no registered device.
        """
        if notif.type not in PUSH_ELIGIBLE_TYPES:
            return 0
        if notif.type == "space_invite" and notif.title_key not in _CONVITES_QUE_INTERROMPEM:
            return 0

        devices = await self.devices.list_for_user(notif.user_id)
        if not devices:
            return 0
        if await self._silenciado_no_push(notif):
            return 0

        data = build_push_data(notif, extra)
        title = _titulo(notif, await self._lingua(notif.user_id))

        messages = [
            PushMessage(
                token=d.push_token,
                title=title,
                body=notif.description or "",
                provider=d.provider,
                data=data,
            )
            for d in devices
        ]

        result = await self.provider.send(messages)
        if result.invalid_tokens:
            pruned = await self.devices.prune_tokens(result.invalid_tokens)
            logger.info("pruned %d invalid push token(s)", pruned)
        return result.sent
