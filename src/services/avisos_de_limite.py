"""Quando um cliente se aproxima do tecto do plano, avisar alguém.

**O defeito.** A lógica dos limiares — 80 %, 95 %, 100 % — existia e funcionava:
detectava a passagem, escrevia no registo de auditoria com
``intent: "tier_limit_warning"``, e o comentário dizia que «os ganchos de email
da Fase 2 lêem estas linhas».

**A Fase 2 nunca foi feita.** Não havia worker nenhum a ler aquilo. O cliente
era BLOQUEADO com um 402 ao chegar aos 100 %, e nunca tinha sido AVISADO a
caminho. Do lado dele: estava a trabalhar, e de repente deixou de poder criar
agentes, sem nada antes.

Um bloqueio sem aviso lê-se como avaria. E um aviso que só existe numa linha
de auditoria que ninguém abre é o mesmo que não existir.

── Dois destinatários, e são mesmo dois ─────────────────────────────────────

**Os administradores do cliente** — são eles que decidem se querem mais um
plano. Vão pelo caminho das notificações da app: aparecem no sino, e o
despachante de push leva-as ao telemóvel. É onde eles já olham.

**Os operadores da plataforma** — a equipa SkyFirst. Um cliente a 95 % é uma
conversa comercial a ter antes de ele bater na parede, não depois. Vão por
email, porque ninguém da equipa vive dentro da app de um cliente.

Avisar só o cliente deixava a SkyFirst a saber das coisas pelo suporte.
Avisar só a SkyFirst deixava o cliente a bater na parede sem perceber.

── O que isto NÃO faz ───────────────────────────────────────────────────────

Não repete. A des-duplicação já existia e é boa: o
``last_threshold_alerted`` guarda os limiares já disparados por recurso e por
período, e este módulo é chamado exactamente onde essa lista é actualizada.
Não acrescentei uma segunda memória — duas memórias do mesmo facto acabam
sempre por discordar.

E **nunca trava o caminho quente**. Isto corre dentro do incremento de um
contador, que acontece a cada agente criado e a cada pergunta. Uma falha de
SMTP não pode impedir alguém de fazer uma pergunta: tudo é melhor-esforço, tal
como já era a escrita da auditoria ao lado.
"""

from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

#: O que cada limiar quer dizer, em português de quem lê.
FRASE: dict = {
    80: (
        "Já usaste {atual} de {limite} {recurso}.",
        "Estás a 80% do teu plano. Ainda dá folga, mas vale a pena saber.",
    ),
    95: (
        "Estás quase no limite de {recurso}: {atual} de {limite}.",
        "A 95% do plano. Quando chegar ao fim, deixa de dar para criar mais.",
    ),
    100: (
        "Chegaste ao limite de {recurso}: {atual} de {limite}.",
        "Para criar mais, é preciso subir de plano.",
    ),
}

#: Como se chamam os recursos para quem lê, e não para quem escreveu a coluna.
NOME_DO_RECURSO: dict = {
    "agents": "agentes",
    "users": "utilizadores",
    "storage": "armazenamento",
    "queries": "perguntas este mês",
}


async def _admins_do_cliente(db) -> List[UUID]:
    """Quem manda neste cliente. Vazio se não der para saber.

    Um `member` não pode mudar de plano; avisá-lo é ruído. Se a consulta
    falhar devolve-se vazio — um aviso a menos é melhor do que um erro no
    caminho de criar um agente.
    """
    try:
        from sqlalchemy import or_, select

        from src.models.user import User

        linhas = (
            await db.execute(
                select(User.id).where(
                    or_(
                        User.role == "super_admin",
                        User.role == "admin",
                        User.role == "owner",  # alias antigo
                    )
                )
            )
        ).scalars().all()
        return list(linhas)
    except Exception as exc:  # noqa: BLE001
        logger.warning("avisos_de_limite: não deu para listar admins: %s", exc)
        return []


def operadores_da_plataforma() -> List[str]:
    """Os emails da equipa SkyFirst que recebem estes avisos.

    Vem das definições. Sem configuração não se inventa destinatário nenhum —
    mandar email para um endereço adivinhado é pior do que não mandar.
    """
    from src.config.settings import settings

    bruto = getattr(settings, "PLATFORM_ALERT_EMAILS", "") or ""
    return [e.strip() for e in bruto.split(",") if e.strip()]


async def avisar(
    db,
    *,
    tenant_id,
    tenant_slug: Optional[str],
    tier: str,
    recurso: str,
    limiar: int,
    atual,
    limite,
) -> None:
    """Avisa os administradores do cliente e os operadores da plataforma.

    Melhor-esforço em tudo. Isto corre dentro do incremento de um contador —
    uma falha de SMTP não pode impedir alguém de fazer uma pergunta.
    """
    nome = NOME_DO_RECURSO.get(recurso, recurso)
    titulo_t, descricao_t = FRASE.get(limiar, FRASE[100])
    titulo = titulo_t.format(atual=atual, limite=limite, recurso=nome)
    descricao = descricao_t.format(atual=atual, limite=limite, recurso=nome)

    # ── Os administradores do cliente, no sino da app ──────────────────
    try:
        from src.schemas.notification import NotificationCreate
        from src.services.notification_service import NotificationService

        servico = NotificationService(db)
        for uid in await _admins_do_cliente(db):
            await servico.create_notification(
                NotificationCreate(
                    user_id=uid,
                    type="PLAN_LIMIT",
                    title=titulo,
                    description=descricao,
                    entity_type="plan",
                    entity_id=str(tenant_id),
                    deep_link="/settings/plan",
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("avisos_de_limite: notificação falhou: %s", exc)

    # ── Os operadores da plataforma, por email ─────────────────────────
    destinos = operadores_da_plataforma()
    if not destinos:
        # Não é um erro — é uma definição em falta. Mas tem de aparecer, senão
        # este caminho volta a ser silencioso, que é o defeito que estamos a
        # corrigir.
        logger.warning(
            "avisos_de_limite: %s chegou a %s%% de %s e NÃO há "
            "PLATFORM_ALERT_EMAILS configurado — ninguém da equipa foi avisado",
            tenant_slug or tenant_id,
            limiar,
            recurso,
        )
        return

    try:
        from src.services.email_service import EmailService

        quem = tenant_slug or str(tenant_id)
        assunto = f"[Sky] {quem} a {limiar}% de {nome} ({tier})"
        corpo = (
            f"<p><b>{quem}</b> chegou a <b>{limiar}%</b> do limite de {nome}.</p>"
            f"<p>Plano: {tier}<br>Atual: {atual}<br>Limite: {limite}</p>"
            f"<p>Aos 100% deixa de conseguir criar — vale a pena falar antes.</p>"
        )
        servico_email = EmailService()
        for destino in destinos:
            servico_email.send_email(
                to_email=destino, subject=assunto, html_content=corpo
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("avisos_de_limite: email falhou: %s", exc)
