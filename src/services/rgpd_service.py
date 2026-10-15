"""RGPD — o que acontece aos dados pessoais depois de uma remoção, e quanto
tempo se guardam os registos técnicos (decisões do Lucas, 15/10/2026).

A política de privacidade diz três coisas; este módulo é o que as torna
verdade:

A) **Remoção pelo admin.** No momento: as sessões morrem (refresh tokens
   revogados, access tokens bloqueados no Redis, e o ``get_current_user``
   recusa quem tem ``deleted_at``) e os aparelhos/push tokens são apagados.
   A conta deixa de poder entrar. Ver :func:`revogar_acessos`.

   **Aos ``ANONIMIZACAO_APOS_REMOCAO_DIAS`` dias** (30): anonimização
   irreversível — nome, email, avatar, MFA, identificadores de SSO, IP/UA
   dos refresh tokens e da auditoria, notificações pessoais. As mensagens,
   conversas e conteúdos de trabalho FICAM (são da organização) mas o autor
   passa a ser «Utilizador removido», porque o nome é sempre lido da linha
   do ``users``. Ver :func:`anonimizar_removidos`. Até lá o admin pode
   restaurar; depois o ``restore_user`` recusa.

B) **Retenção de ``RETENCAO_AUDITORIA_DIAS`` (365)** para a auditoria
   (``audit_events``, ``internal_console_audit``,
   ``console_impersonation_sessions``) e de ``RETENCAO_SESSOES_EXPIRADAS_DIAS``
   (30) para refresh tokens já expirados, que guardam IP e user agent. Ver
   :func:`aplicar_retencao`. A retenção do sky-ai (``query_audit_log``,
   ``prompt_security_audit``, ``security_alerts``) é feita pelo próprio
   sky-ai, chamado por base pela tarefa diária.

Tudo idempotente (a segunda passagem não encontra nada) e com dry-run: com
``dry_run=True`` só se conta, nada se escreve. Os resultados são contagens —
nunca emails, nomes ou IDs de pessoas — para poderem ir para logs e
métricas sem levar dados pessoais.

── Porque a auditoria aceita UPDATE/DELETE aqui ─────────────────────────────

``audit_events`` tem gatilhos que recusam UPDATE e DELETE. A migração
``rgpd_anonimizacao_retencao_20261015`` abre UMA excepção: dentro de uma
transacção que ligou ``sky.rgpd_manutencao``. Mesmo aí o UPDATE só pode
mudar os campos pessoais — os que entram na cadeia de hashes ficam iguais,
por isso ``AuditService.verify_chain`` continua válido. Apagar as linhas
mais antigas também não parte a cadeia: a verificação começa na primeira
linha que resta.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

NOME_ANONIMO = "Utilizador removido"
# Não é ``@invalid``: o ``EmailStr`` do ``UserResponse`` (email-validator)
# recusa domínios de uso especial (.invalid, .local, .test) e qualquer ecrã
# que serializasse a conta anonimizada rebentava com 500. Um subdomínio
# nosso, sem MX, não entrega correio a ninguém e passa na validação.
DOMINIO_ANONIMO = "removido.skyfirstlabs.com"


def email_anonimo() -> str:
    """``removido-<uuid aleatório>@removido.skyfirstlabs.com``.

    Aleatório e não derivado do id nem do email: não há como voltar atrás.
    Único, por isso não colide com o índice único de ``users.email``.
    """
    return f"removido-{uuid.uuid4().hex}@{DOMINIO_ANONIMO}"


def _agora() -> datetime:
    return datetime.now(timezone.utc)


async def _ligar_manutencao(db: AsyncSession) -> None:
    """Abre a excepção dos gatilhos de ``audit_events`` para ESTA transacção.

    ``set_config(..., true)`` é local à transacção: acaba no commit ou no
    rollback. Fora do Postgres (testes em SQLite) não há gatilhos.
    """
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('sky.rgpd_manutencao', 'on', true)"))


# ── A) No momento da remoção ─────────────────────────────────────────────


async def revogar_acessos(db: AsyncSession, user_id: UUID) -> Dict[str, int]:
    """Mata as sessões e apaga os aparelhos de ``user_id``. Não faz commit.

    - refresh tokens ainda vivos → ``revoked_at = agora`` (o ``/auth/refresh``
      passa a dar 401);
    - aparelhos (push tokens) → apagados, para nenhuma notificação chegar ao
      telemóvel de quem saiu.

    O bloqueio dos access tokens já emitidos é feito por quem chama, depois
    do commit (:func:`bloquear_access_tokens`) — e, mesmo sem Redis, o
    ``get_current_user`` recusa um utilizador com ``deleted_at``.
    """
    from src.models.device import Device
    from src.models.user import RefreshToken

    r_tokens = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_agora())
    )
    r_devices = await db.execute(delete(Device).where(Device.user_id == user_id))
    await db.flush()
    return {
        "refresh_tokens_revogados": int(r_tokens.rowcount or 0),
        "aparelhos_apagados": int(r_devices.rowcount or 0),
    }


async def bloquear_access_tokens(user_id: UUID) -> None:
    """Access tokens emitidos até agora deixam de valer (Redis, best-effort)."""
    try:
        from src.core.token_blocklist import revoke_user_tokens

        await revoke_user_tokens(str(user_id), issued_before_epoch=int(_agora().timestamp()) + 1)
    except Exception as exc:  # noqa: BLE001 — o get_current_user já recusa
        logger.warning("rgpd: bloqueio de access tokens falhou: %s", type(exc).__name__)


# ── A) Aos 30 dias ───────────────────────────────────────────────────────


def _candidatos(corte: datetime):
    """Removidos antes de ``corte`` e ainda por anonimizar.

    Nunca o utilizador de sistema nem operadores Sky (o ``delete_user`` já
    os protege; isto é a segunda guarda).
    """
    from src.models.user import User

    return (
        User.deleted_at.is_not(None),
        User.deleted_at < corte,
        User.anonymized_at.is_(None),
        User.is_sky_operator.is_(False),
        User.status != "sistema",
    )


@dataclass
class Resultado:
    """Contagens de uma passagem numa base. Sem dados pessoais."""

    dry_run: bool
    contagens: Dict[str, int] = field(default_factory=dict)
    falhas: List[str] = field(default_factory=list)

    def somar(self, chave: str, n: int) -> None:
        self.contagens[chave] = self.contagens.get(chave, 0) + int(n or 0)

    def como_dict(self) -> Dict[str, Any]:
        return {"dry_run": self.dry_run, **self.contagens, "falhas": list(self.falhas)}


async def anonimizar_removidos(
    db: AsyncSession,
    *,
    dias: int,
    dry_run: bool,
    agora: Optional[datetime] = None,
) -> Resultado:
    """Anonimiza quem foi removido há mais de ``dias`` dias. Faz commit.

    Idempotente: ``anonymized_at`` marca quem já foi tratado. Com
    ``dry_run`` só conta os candidatos.
    """
    from src.models.audit import AuditEvent
    from src.models.device import Device
    from src.models.notification import Notification, NotificationPreference
    from src.models.user import RefreshToken, User

    if dias < 1:
        raise ValueError("ANONIMIZACAO_APOS_REMOCAO_DIAS tem de ser >= 1")
    agora = agora or _agora()
    corte = agora - timedelta(days=dias)
    res = Resultado(dry_run=dry_run)

    ids: List[UUID] = list(
        (await db.execute(select(User.id).where(*_candidatos(corte)))).scalars().all()
    )
    res.somar("utilizadores_por_anonimizar", len(ids))
    if dry_run or not ids:
        return res

    await _ligar_manutencao(db)
    for uid in ids:
        # Um utilizador por savepoint: um que falhe não desfaz os outros.
        try:
            async with db.begin_nested():
                await db.execute(
                    update(User)
                    .where(User.id == uid, User.anonymized_at.is_(None))
                    .values(
                        email=email_anonimo(),
                        name=NOME_ANONIMO,
                        avatar=None,
                        # Hash impossível: nenhuma password lhe corresponde.
                        password_hash="!removido",
                        role="member",
                        email_verified=False,
                        email_verified_at=None,
                        last_login_at=None,
                        last_active_at=None,
                        status="offline",
                        preferences={},
                        selected_domain=None,
                        auth0_id=None,
                        auth_provider_id=None,
                        sso_metadata=None,
                        invite_token=None,
                        invite_expires_at=None,
                        password_reset_token=None,
                        password_reset_expires_at=None,
                        mfa_enabled=False,
                        mfa_secret_encrypted=None,
                        mfa_recovery_codes_encrypted=None,
                        mfa_enrolled_at=None,
                        mfa_last_used_at=None,
                        anonymized_at=agora,
                    )
                )
                # Sessões: o registo inteiro tem IP e UA e já não serve a
                # ninguém (estavam revogadas desde a remoção).
                r = await db.execute(delete(RefreshToken).where(RefreshToken.user_id == uid))
                res.somar("refresh_tokens_apagados", r.rowcount)
                r = await db.execute(delete(Device).where(Device.user_id == uid))
                res.somar("aparelhos_apagados", r.rowcount)
                # A caixa de notificações é da pessoa, não da organização.
                r = await db.execute(delete(Notification).where(Notification.user_id == uid))
                res.somar("notificacoes_apagadas", r.rowcount)
                r = await db.execute(
                    delete(NotificationPreference).where(NotificationPreference.user_id == uid)
                )
                res.somar("preferencias_apagadas", r.rowcount)
                # Auditoria: a linha fica (é prova do que aconteceu), sem o
                # email, o IP e o browser de quem agiu. O actor_id fica —
                # aponta para uma linha que já não identifica ninguém.
                r = await db.execute(
                    update(AuditEvent)
                    .where(
                        AuditEvent.actor_id == uid,
                        (AuditEvent.actor_email.is_not(None))
                        | (AuditEvent.ip.is_not(None))
                        | (AuditEvent.user_agent.is_not(None)),
                    )
                    .values(actor_email=None, ip=None, user_agent=None)
                )
                res.somar("auditoria_linhas_anonimizadas", r.rowcount)
            res.somar("utilizadores_anonimizados", 1)
        except Exception as exc:  # noqa: BLE001
            res.falhas.append(f"anonimizar:{type(exc).__name__}")
            logger.warning("rgpd: anonimização de um utilizador falhou: %s", type(exc).__name__)
    await db.commit()
    return res


# ── B) Retenção ──────────────────────────────────────────────────────────


async def aplicar_retencao(
    db: AsyncSession,
    *,
    dias_auditoria: int,
    dias_sessoes_expiradas: int,
    dry_run: bool,
    agora: Optional[datetime] = None,
) -> Resultado:
    """Apaga registos técnicos mais velhos do que a retenção. Faz commit.

    Uma tabela que falhe (não existe nesta base, sem permissão) é registada
    em ``falhas`` e as outras seguem.
    """
    from src.models.audit import AuditEvent
    from src.models.internal_console import (
        ConsoleImpersonationSession,
        InternalConsoleAudit,
    )
    from src.models.user import RefreshToken

    if dias_auditoria < 30 or dias_sessoes_expiradas < 1:
        # Uma variável de ambiente mal escrita (0, 1) apagava a auditoria
        # toda. Melhor não correr do que correr assim.
        raise ValueError("retenção demasiado curta (auditoria >= 30, sessões >= 1)")
    agora = agora or _agora()
    corte = agora - timedelta(days=dias_auditoria)
    corte_sessoes = agora - timedelta(days=dias_sessoes_expiradas)
    res = Resultado(dry_run=dry_run)

    passos = [
        ("audit_events", AuditEvent, AuditEvent.occurred_at < corte),
        ("internal_console_audit", InternalConsoleAudit, InternalConsoleAudit.timestamp < corte),
        (
            "console_impersonation_sessions",
            ConsoleImpersonationSession,
            func.coalesce(
                ConsoleImpersonationSession.ended_at, ConsoleImpersonationSession.started_at
            )
            < corte,
        ),
        ("refresh_tokens_expirados", RefreshToken, RefreshToken.expires_at < corte_sessoes),
    ]

    if not dry_run:
        await _ligar_manutencao(db)
    for nome, modelo, condicao in passos:
        try:
            async with db.begin_nested():
                n = (
                    await db.execute(select(func.count()).select_from(modelo).where(condicao))
                ).scalar() or 0
                if n and not dry_run:
                    await db.execute(delete(modelo).where(condicao))
            res.somar(f"{nome}_a_apagar" if dry_run else f"{nome}_apagados", n)
        except Exception as exc:  # noqa: BLE001
            res.falhas.append(f"{nome}:{type(exc).__name__}")
            logger.warning("rgpd: retenção de %s falhou: %s", nome, type(exc).__name__)
    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return res
