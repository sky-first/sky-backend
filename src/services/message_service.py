"""Message service — add, list, pin, fork.

RBAC for messages piggybacks on the parent conversation:
  - list / add  → anyone who can view the conversation
  - pin         → anyone who can view the conversation AND has widgets.create
  - fork        → anyone who can view the conversation; the fork is created
                  as a personal conversation owned by the caller

Pin concurrency (use case A11) is enforced by a partial unique index on
widgets.pinned_message_id: the second concurrent INSERT hits the
constraint and we return the pre-existing widget instead of raising.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.core.permissions import is_tenant_admin
from src.models.conversation import Conversation, Message
from src.models.user import User
from src.models.widget import Widget
from src.repositories.conversation import ConversationRepository
from src.repositories.message import MessageRepository
from src.schemas.message import ForkRequest, MessageCreate, MessageResponse, PinRequest
from src.services.conversation_service import ConversationService

import logging

logger = logging.getLogger(__name__)

try:
    # chat-threads PR4: broadcast new messages on the page WebSocket so
    # every connected peer renders the new comment/question/ai_response
    # without polling. Import is wrapped so circular-import or
    # not-loaded-yet doesn't crash CLI / migration code paths.
    from src.api.v1.chat_ws import broadcast_event_nowait
except Exception:  # pragma: no cover — relay is optional

    def broadcast_event_nowait(*args, **kwargs):
        return None


# Only the AI service / agent runtime should write these. Humans submit
# user messages; everything else is produced server-side.
_HUMAN_ROLE = "user"


#: Quanto do texto cabe num título antes de deixar de ajudar a distinguir uma
#: conversa da seguinte. Sessenta caracteres é o que a lista mostra sem cortar
#: em quase todos os telemóveis.
_MAX_TITULO = 60


def _titulo_a_partir_de(texto: str) -> str:
    """A primeira frase, encurtada — o nome que a conversa passa a ter.

    Não chama modelo nenhum. Um título é para distinguir uma linha na lista, e
    para isso a pergunta que a originou serve tão bem como um resumo — sem
    latência, sem custo, e sem o risco de a lista mudar de nome sozinha porque
    o modelo respondeu diferente à segunda.

    Corta na fronteira de uma palavra: "Como fechou Julho contra o orç…" lê-se,
    "Como fechou Julho contra o o…" tropeça.
    """
    limpo = " ".join((texto or "").split())
    if not limpo:
        return ""
    # A primeira frase, quando é curta o suficiente para chegar.
    for marca in (". ", "? ", "! ", "\n"):
        corte = limpo.find(marca)
        if 0 < corte <= _MAX_TITULO:
            return limpo[: corte + 1].strip()
    if len(limpo) <= _MAX_TITULO:
        return limpo
    cortado = limpo[:_MAX_TITULO]
    espaco = cortado.rfind(" ")
    if espaco > _MAX_TITULO // 2:
        cortado = cortado[:espaco]
    return cortado.rstrip(" ,;:") + "…"


def _display_name(user: Optional[User]) -> Optional[str]:
    """Human-friendly author label: full name, else the email local part."""
    if user is None:
        return None
    name = (getattr(user, "name", None) or "").strip()
    if name:
        return name
    email = getattr(user, "email", None)
    return email.split("@")[0] if email else None


class MessageService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MessageRepository(db)
        self.conv_repo = ConversationRepository(db)
        self.conv_service = ConversationService(db)

    # ─── Helpers ─────────────────────────────────────────────────────────

    async def _load_viewable_conversation(self, conversation_id: UUID, user: User) -> Conversation:
        conv = await self.conv_repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self.conv_service._can_view(conv, user):
            # Hide existence.
            raise NotFoundError("Conversation not found")
        return conv

    async def _attach_author_names(self, messages: List[Message]) -> None:
        """Resolve each message author's display name and attach it as the
        transient ``author_name`` attribute so MessageResponse serialises it.

        One batched query for the distinct authors in the list. AI/system
        rows (user_id NULL) and legacy rows stay None.
        """
        user_ids = {m.user_id for m in messages if m.user_id is not None}
        names: dict = {}
        if user_ids:
            rows = await self.db.execute(
                select(User.id, User.name, User.email).where(User.id.in_(user_ids))
            )
            for uid, name, email in rows.all():
                label = (name or "").strip() or (email.split("@")[0] if email else None)
                names[uid] = label
        for m in messages:
            m.author_name = names.get(m.user_id) if m.user_id else None

    # ─── Create ──────────────────────────────────────────────────────────

    async def create(self, conversation_id: UUID, user: User, payload: MessageCreate) -> Message:
        conv = await self._load_viewable_conversation(conversation_id, user)

        if payload.role != _HUMAN_ROLE:
            # Non-human roles are produced by the backend itself on behalf
            # of the AI service or an agent run. An HTTP caller cannot
            # impersonate the assistant/system.
            raise ForbiddenError("Only role='user' messages can be created via this endpoint")

        # chat-threads-master-plan PR1: derive `kind` and enforce
        # owner-gating for questions.
        #   - kind='question' (or unspecified) → fires AI; only the
        #     conversation owner (creator) may submit. Page editors
        #     and admins also pass (they can run AI on shared threads
        #     to unblock the team).
        #   - kind='comment' → any viewer may post; never fires AI.
        kind = payload.kind or "question"
        if kind == "question":
            if conv.created_by != user.id and not is_tenant_admin(user):
                # Mirror "owner gates AI re-runs in that thread" from
                # the chat-threads-master-plan. Non-owners must post
                # comments instead, which the FE renders as the "Leave
                # comment" button.
                raise ForbiddenError(
                    "Only the conversation owner can post a question; "
                    "non-owners can leave comments instead"
                )
        elif kind != "comment":
            # Should be unreachable thanks to the pattern validator on the
            # schema, but guard explicitly so the service is the canonical
            # policy gate.
            raise ForbiddenError(
                "Invalid message kind; only 'question' and 'comment' are " "accepted from clients"
            )

        msg = await self.repo.create(
            conversation_id=conv.id,
            role=payload.role,
            kind=kind,
            content=payload.content,
            user_id=user.id,
            query_id=payload.query_id,
            cost_tokens=payload.cost_tokens,
            cost_usd=payload.cost_usd,
            parent_message_id=payload.parent_message_id,
        )

        # A conversa ganha nome na primeira coisa que lá se escreve.
        #
        # Nascia sem título e ficava sem título para sempre: a lista de
        # conversas era uma coluna de "Sem título", e o cabeçalho da conversa
        # aberta dizia o mesmo. Quem tem cinco conversas não distingue nenhuma.
        #
        # O nome sai da primeira mensagem, como no ChatGPT e no Claude. Aqui e
        # não no cliente, por duas razões: a web e a app passam pelo mesmo
        # sítio, e quem renomeia à mão manda um título explícito que isto não
        # pode pisar — daí só acontecer quando ainda não há nenhum.
        if not (conv.title or "").strip():
            conv.title = _titulo_a_partir_de(payload.content)

        # Touch the conversation so list ordering surfaces it as recent.
        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(msg)

        # Avisar quem foi mencionado.
        #
        # A app já extraía `@nome` do texto há muito — e deitava fora o
        # resultado. O `@` parecia funcionar e não notificava ninguém: a
        # pessoa mencionada nunca sabia. É o tipo de falha que só se descobre
        # quando alguém pergunta "então não viste o que te escrevi?".
        #
        # Vem por id, do selector da app. Adivinhar a partir do texto era
        # arriscar mandar a notificação à pessoa errada — pior do que não
        # mandar nenhuma.
        await self._notificar_mencionados(payload.mentions, user, conv, payload.content)

        # E avisar quem já participou na conversa.
        #
        # Sem isto a colaboração morria em silêncio: só a menção explícita
        # notificava, portanto comentar a resposta de alguém não avisava
        # ninguém. Se essa pessoa tinha fechado a app, a observação ficava ali
        # para sempre — e ela nunca soube que lhe tinham respondido.
        #
        # Depois dos mencionados e a saber quem eles são, para ninguém receber
        # dois avisos da mesma mensagem.
        await self._notificar_participantes(
            user, conv, payload.content, ja_avisados=set(payload.mentions or [])
        )

        # The writer is the caller — stamp their display name so the
        # broadcast + HTTP response attribute the message to the real
        # author for every collaborator (not the local viewer's name).
        msg.author_name = _display_name(user)

        # PR4: broadcast to every WS subscriber on this page. Fire-and-forget
        # so the HTTP response doesn't wait on peer acks.
        broadcast_event_nowait(
            str(conv.page_id),
            "message.created",
            MessageResponse.model_validate(msg).model_dump(mode="json"),
        )

        return msg

    # ─── List ────────────────────────────────────────────────────────────

    async def list_for_conversation(
        self,
        conversation_id: UUID,
        user: User,
        *,
        limit: int = 50,
        cursor: Optional[datetime] = None,
    ) -> List[Message]:
        await self._load_viewable_conversation(conversation_id, user)
        messages = await self.repo.list_for_conversation(
            conversation_id=conversation_id, limit=limit, cursor=cursor
        )
        await self._attach_author_names(messages)
        return messages

    # ─── Ask-AI bundling (chat-threads-master-plan PR2) ─────────────────

    async def list_pending_comments(self, conversation_id: UUID, user: User) -> List[Message]:
        """Comments since the last ai_response, not yet incorporated.

        Used by the FE to preview "X comments will be included" before the
        owner fires a new question, and by the bundling code below to
        assemble the prompt.
        """
        await self._load_viewable_conversation(conversation_id, user)
        return await self.repo.list_pending_comments(conversation_id=conversation_id)

    async def ask_ai_with_bundle(
        self,
        conversation_id: UUID,
        user: User,
        question_content: str,
        ai_answer_content: str,
        *,
        query_id: Optional[UUID] = None,
        tier: Optional[str] = None,
        duration_ms: Optional[int] = None,
        cost_tokens: Optional[int] = None,
        cost_usd: Optional[Decimal] = None,
    ) -> dict:
        """Owner-gated bundle flow.

        1. Load pending comments since the last AI response.
        2. Insert the question (kind='question').
        3. Insert the AI response (kind='ai_response') with parent =
           question.id.
        4. Stamp each bundled comment's incorporated_in_message_id =
           ai_response.id so the FE renders the "incorporated in #N"
           badge.

        Returns the bundle dict {question, ai_response, incorporated:
        [comment_ids]} so the caller can ship them on the WebSocket in
        a single broadcast.

        The AI call itself is the *caller's* responsibility — this
        service stays pure-DB so it doesn't pull the AI client into the
        chat module. The caller passes the answer in. PR4 wires the
        broadcast.
        """
        conv = await self._load_viewable_conversation(conversation_id, user)
        if conv.created_by != user.id and not is_tenant_admin(user):
            raise ForbiddenError("Only the conversation owner can fire an Ask-AI bundle")

        pending = await self.repo.list_pending_comments(conversation_id=conversation_id)

        # 2. Question — authored by the owner firing the bundle.
        question = await self.repo.create(
            conversation_id=conv.id,
            role="user",
            kind="question",
            content=question_content,
            user_id=user.id,
            query_id=query_id,
        )

        # 3. AI response (kind=ai_response, role=assistant)
        ai_response = await self.repo.create(
            conversation_id=conv.id,
            role="assistant",
            kind="ai_response",
            content=ai_answer_content,
            query_id=query_id,
            tier=tier,
            duration_ms=duration_ms,
            cost_tokens=cost_tokens,
            cost_usd=cost_usd,
            parent_message_id=question.id,
        )

        # 4. Stamp incorporated comments
        if pending:
            await self.repo.mark_incorporated(
                message_ids=[c.id for c in pending],
                ai_response_id=ai_response.id,
            )

        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(question)
        await self.db.refresh(ai_response)

        # Attribute the question to its author; the AI response stays
        # authorless (rendered as the assistant).
        question.author_name = _display_name(user)
        ai_response.author_name = None

        # PR4: broadcast the bundle so peers render the question/AI pair
        # immediately. We send both events (clients can render the AI
        # answer as it lands while keeping the question above it).
        page_id = str(conv.page_id)
        broadcast_event_nowait(
            page_id,
            "message.created",
            MessageResponse.model_validate(question).model_dump(mode="json"),
        )
        broadcast_event_nowait(
            page_id,
            "message.created",
            MessageResponse.model_validate(ai_response).model_dump(mode="json"),
        )

        return {
            "question": question,
            "ai_response": ai_response,
            "incorporated_message_ids": [c.id for c in pending],
        }

    @staticmethod
    def build_bundled_prompt(question_content: str, pending_comments: List[Message]) -> str:
        """Pure helper: stitches the question + pending comments into a
        single LLM-ready prompt.

        The LLM is asked to (a) skim the discussion, (b) reach a
        "consensus" reading, then (c) answer the question grounded in
        that consensus. Caller passes the resulting text to whatever
        AI client is in use; we keep the prompt assembly here so unit
        tests can lock in the format.
        """
        if not pending_comments:
            return question_content

        comments_block = "\n".join(f"- {c.content}" for c in pending_comments)
        return (
            "You are answering a follow-up question on a shared discussion. "
            "Below are the comments the team posted since your last answer. "
            "Briefly synthesise the consensus, then answer the question.\n\n"
            f"Team comments since last answer:\n{comments_block}\n\n"
            f"Question:\n{question_content}"
        )

    # ─── Pin ─────────────────────────────────────────────────────────────

    async def pin_message(self, message_id: UUID, user: User, payload: PinRequest) -> Widget:
        """Materialise a widget anchored to this message.

        A11: concurrent pins of the same message resolve to a single widget.
        The partial unique index on widgets.pinned_message_id enforces
        this. On IntegrityError we refetch and return the winning widget.
        """
        msg = await self.repo.get_by_id(message_id)
        if not msg:
            raise NotFoundError("Message not found")

        # RBAC: require view of the parent conversation.
        conv = await self._load_viewable_conversation(msg.conversation_id, user)

        # Only assistant messages produce meaningful insights. Pinning a
        # user question doesn't make sense and would just clutter the DB.
        if msg.role != "assistant":
            raise BadRequestError("Only assistant messages can be pinned")

        # Uma resposta que cruzou projetos não se publica.
        #
        # É o travão da opção C, e está aqui — na saída — de propósito. Quem
        # cruzou já tinha acesso a cada peça; o que ninguém aprovou foi a
        # **combinação**. Quem deu acesso aos salários deu-o no contexto do
        # projeto de RH, não para o gráfico de salários por vendedor aparecer no
        # projeto Comercial.
        #
        # Não é uma prisão: copiar e colar continua a existir e não conseguimos
        # impedi-lo. É dissuasão com registo, e está escrito para ninguém vender
        # isto como garantia.
        if getattr(msg, "cruzou_projetos", False):
            raise BadRequestError(
                "Esta resposta cruzou vários projetos e não pode ser fixada. "
                "Cria um projeto com estes dados para a poderes partilhar."
            )

        # Fast-path: message already pinned → return its widget.
        if msg.pinned_widget_id:
            existing = await self.db.execute(
                select(Widget).where(Widget.id == msg.pinned_widget_id)
            )
            winner = existing.scalar_one_or_none()
            if winner is not None:
                return winner

        # Create the widget. Title defaults to the first line of the
        # message content truncated to 255 chars.
        title = payload.title or msg.content.splitlines()[0][:255] if msg.content else "Insight"
        widget = Widget(
            page_id=payload.page_id,
            type=payload.widget_type,
            title=title,
            position=payload.position or {"x": 0, "y": 0},
            size=payload.size or {"width": 400, "height": 300},
            data={},
            conversation_id=conv.id,
            pinned_message_id=msg.id,
            created_by=user.id,
        )
        self.db.add(widget)
        try:
            await self.db.flush()
        except IntegrityError:
            # A concurrent request already pinned this message — fetch and
            # return the existing widget.
            await self.db.rollback()
            existing = await self.db.execute(
                select(Widget).where(Widget.pinned_message_id == msg.id)
            )
            winner = existing.scalar_one_or_none()
            if winner is None:
                # Extremely unlikely: index raised but row not visible.
                raise
            return winner

        # Back-link the message to the widget so later reads are cheap.
        msg.pinned_widget_id = widget.id
        await self.db.commit()
        await self.db.refresh(widget)
        return widget

    # ─── Fork ────────────────────────────────────────────────────────────

    async def fork(self, conversation_id: UUID, user: User, payload: ForkRequest) -> Conversation:
        """Branch a conversation: create a new thread that contains every
        message up to and including `from_message_id`, owned by the caller.

        The fork is always personal (no space / crew scope) because the
        branch carries the caller's intent — if they want to share it, they
        archive the original and reshare the branched one explicitly.
        """
        parent = await self._load_viewable_conversation(conversation_id, user)
        messages = await self.repo.list_up_to(
            conversation_id=parent.id, until_message_id=payload.from_message_id
        )
        if not messages:
            raise BadRequestError("from_message_id not in this conversation")

        child = await self.conv_repo.create(
            page_id=parent.page_id,
            created_by=user.id,
            space_id=None,
            crew_id=None,
            title=f"Branch — {parent.title or 'Conversation'}",
        )
        # Copy messages. We keep the original created_at order by bumping
        # with microsecond offsets; the exact timestamps aren't load-bearing
        # for the branched thread (the parent remains the canonical log).
        base = datetime.utcnow()
        for idx, src in enumerate(messages):
            copied = Message(
                conversation_id=child.id,
                role=src.role,
                content=src.content,
                user_id=src.user_id,
                query_id=src.query_id,
                cost_tokens=src.cost_tokens,
                cost_usd=src.cost_usd,
                created_at=base.replace(microsecond=(base.microsecond + idx) % 1_000_000),
            )
            self.db.add(copied)

        await self.db.commit()
        await self.db.refresh(child)
        return child

    async def toggle_reaction(
        self,
        conversation_id: UUID,
        message_id: UUID,
        emoji: str,
        user: User,
    ) -> Message:
        """Toggle the caller's reaction with this emoji on the message.

        Idempotent: if the user is already in the emoji's list, they
        come out; otherwise they go in. Empty lists are pruned so the
        JSONB stays compact.
        """
        # RBAC: caller must be able to see the parent conversation
        # — same gate Message.create uses.
        conv = await self.conv_repo.get_by_id(conversation_id)
        if conv is None:
            raise NotFoundError("conversation not found")
        if not await self.conv_service._can_view(conv, user):
            raise ForbiddenError("you cannot react in this conversation")

        msg = await self.db.get(Message, message_id)
        if msg is None or msg.conversation_id != conversation_id:
            raise NotFoundError("message not found in this conversation")

        # Copy-on-write so SQLAlchemy detects the change.
        reactions: dict = dict(msg.reactions or {})
        bucket = list(reactions.get(emoji, []))
        uid = str(user.id)
        if uid in bucket:
            bucket.remove(uid)
        else:
            bucket.append(uid)
        if bucket:
            reactions[emoji] = bucket
        else:
            reactions.pop(emoji, None)
        msg.reactions = reactions

        await self.db.commit()
        await self.db.refresh(msg)
        await self._attach_author_names([msg])

        # Best-effort WS broadcast so peers see the reaction update
        # in real time. The relay signature is (page_id, event_type,
        # payload) — match the existing "message.created" envelope.
        try:
            broadcast_event_nowait(
                str(conv.page_id),
                "message.reaction",
                {
                    "conversation_id": str(conv.id),
                    "message_id": str(msg.id),
                    "reactions": reactions,
                },
            )
        except Exception:  # pragma: no cover — relay is optional
            pass

        return msg

    async def _notificar_mencionados(self, mentions, autor, conv, conteudo: str) -> None:
        """Uma notificação por pessoa mencionada, na língua dela.

        Nunca notifica o próprio: mencionar-se a si mesmo acontece ao
        escrever depressa, e uma notificação sobre o que acabámos de
        escrever é ruído.

        Falhar aqui não pode derrubar a mensagem — ela já está gravada, e
        perder o texto por causa de um aviso seria trocar o essencial pelo
        acessório.
        """
        destinatarios = [m for m in (mentions or []) if m != autor.id]
        if not destinatarios:
            return
        try:
            from src.core.locale import get_message, normalize_locale
            from src.models.notification import NotificationType
            from src.schemas.notification import NotificationCreate
            from src.services.notification_service import NotificationService

            rows = await self.db.execute(
                select(User.id, User.preferences).where(User.id.in_(destinatarios))
            )
            prefs_por_id = {rid: prefs for rid, prefs in rows.all()}
            servico = NotificationService(self.db)
            excerto = (conteudo or "")[:50]
            for uid in destinatarios:
                prefs = prefs_por_id.get(uid) or {}
                locale = normalize_locale(
                    prefs.get("language") if isinstance(prefs, dict) else None
                )
                await servico.create(
                    NotificationCreate(
                        user_id=uid,
                        type=NotificationType.COMMENT_MENTION,
                        title=get_message("notif_comment_mention_title", locale),
                        description=get_message("notif_comment_mention_desc", locale).format(
                            snippet=excerto
                        ),
                        entity_type="conversation",
                        entity_id=str(conv.id),
                        deep_link=f"/page?id={conv.page_id}&conversation={conv.id}",
                        title_key="notif_comment_mention_title",
                        description_key="notif_comment_mention_desc",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mencao_nao_notificada", extra={"conversa": str(conv.id), "erro": str(exc)}
            )

    async def _notificar_participantes(
        self, autor, conv, conteudo: str, *, ja_avisados: set
    ) -> None:
        """Avisa quem já escreveu nesta conversa, mais quem a começou.

        A regra é a do Slack e do Teams: quem entrou numa discussão quer saber
        quando ela continua. Não se avisa o projeto inteiro — só quem já
        demonstrou interesse ao escrever lá — senão passava a ser ruído e as
        pessoas desligavam os avisos todos.

        Nunca notifica:
          - o próprio autor;
          - quem já foi notificado pela menção (`ja_avisados`), para a mesma
            mensagem não chegar duas vezes.

        Falhar aqui não pode derrubar a mensagem: ela já está gravada, e perder
        o texto por causa de um aviso seria trocar o essencial pelo acessório.
        """
        try:
            from sqlalchemy import select as _select

            from src.core.locale import get_message, normalize_locale
            from src.models.conversation import Message as _Message
            from src.models.notification import NotificationType
            from src.models.user import User as _User
            from src.schemas.notification import NotificationCreate
            from src.services.notification_service import NotificationService

            rows = await self.db.execute(
                _select(_Message.user_id)
                .where(_Message.conversation_id == conv.id, _Message.user_id.isnot(None))
                .distinct()
            )
            destinatarios = {uid for (uid,) in rows.all()}
            if conv.created_by:
                destinatarios.add(conv.created_by)
            destinatarios -= {autor.id}
            destinatarios -= ja_avisados
            if not destinatarios:
                return

            prefs_rows = await self.db.execute(
                _select(_User.id, _User.preferences).where(_User.id.in_(destinatarios))
            )
            prefs_por_id = {rid: prefs for rid, prefs in prefs_rows.all()}

            servico = NotificationService(self.db)
            excerto = (conteudo or "")[:50]
            nome_autor = _display_name(autor)
            titulo_conversa = (conv.title or "").strip() or excerto
            for uid in destinatarios:
                prefs = prefs_por_id.get(uid) or {}
                locale = normalize_locale(
                    prefs.get("language") if isinstance(prefs, dict) else None
                )
                params_titulo = {"autor": nome_autor, "conversa": titulo_conversa}
                await servico.create(
                    NotificationCreate(
                        user_id=uid,
                        type=NotificationType.CONVERSATION_REPLY,
                        title=get_message("notif_conversation_reply_title", locale).format(
                            **params_titulo
                        ),
                        description=get_message(
                            "notif_conversation_reply_desc", locale
                        ).format(snippet=excerto),
                        entity_type="conversation",
                        entity_id=str(conv.id),
                        deep_link=f"/page?id={conv.page_id}&conversation={conv.id}",
                        title_key="notif_conversation_reply_title",
                        title_params=params_titulo,
                        description_key="notif_conversation_reply_desc",
                        description_params={"snippet": excerto},
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("aviso de participantes falhou: %s", exc)
