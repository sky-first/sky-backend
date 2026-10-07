"""Conversation and Message models — the first-class Q&A thread.

A conversation is the persistent thread a user navigates. It is scoped to a
page (always) and optionally to a space / crew for collaborative contexts.
Widgets/insights reference back to the conversation (and the specific message)
they were pinned from, so the user can always re-enter the thread that
produced an insight with full history.
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class Conversation(Base):
    """A Q&A thread scoped to a page (and optionally a space/crew)."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Chat session this thread belongs to ("Chat 1", "Chat 2", …). Nullable
    # so legacy threads (and the SET NULL on a hard-deleted session) keep
    # working; the backfill migration assigns every existing thread to a
    # default "Chat 1" per page, and the create endpoint tags new threads
    # with the active session.
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(500), nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    archived_at = Column(DateTime(timezone=True), nullable=True)
    # Thread state (added in chat-threads-master-plan PR1, 2026-05-20).
    # resolved_at: owner or page-editor closed the thread (/resolve).
    # pinned_message_id: message highlighted at top of the thread (/pin).
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    pinned_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    # The `foreign_keys` is required because Conversation also points at
    # messages.id via pinned_message_id (chat-threads PR1), so SQLAlchemy
    # can no longer infer which FK relates the parent/child collection.
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        foreign_keys="Message.conversation_id",
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, page_id={self.page_id}, title={self.title})>"


class Message(Base):
    """One message within a conversation."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    #: A resposta nasceu de mais do que um projeto (modo cross-project).
    #: Serve para recusar fixá-la numa página: o risco do cruzamento não é
    #: a leitura — é a redistribuição.
    cruzou_projetos = Column(Boolean, nullable=False, default=False, server_default="false")
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)  # 'user' | 'assistant' | 'system'
    # Author of the message — the user who actually wrote it. NULL for
    # assistant ('ai_response') and system messages, and for legacy rows
    # created before collaborative attribution landed (chat
    # author-attribution, 2026-06-02). Shared (space/crew) chats render
    # the real author to every collaborator from this instead of falling
    # back to the local viewer's name. ON DELETE SET NULL keeps the
    # message if the author's account is removed.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ``kind`` further partitions the user/assistant axis along the
    # collaborative-thread semantics (chat-threads-master-plan PR1,
    # 2026-05-20):
    #   - question     → owner's prompt that fires AI
    #   - ai_response  → LLM reply
    #   - comment      → non-owner discussion (does NOT fire AI)
    #   - system       → pin/resolve/transfer audit events
    kind = Column(String(20), nullable=True)
    content = Column(Text, nullable=False)
    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_queries.id", ondelete="SET NULL"),
        nullable=True,
    )
    cost_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(10, 4), nullable=True)
    # Insights-Analytics — see src/services/insights_tier.py.
    tier = Column(String(2), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    # BE-04 (Sky Mobile) — how the message was created. A 'voice' message
    # shows the mic glyph in the transcript and flips its conversation's
    # voice/text icon in History. Default 'text' so every existing row and
    # every typed message is unaffected; the voice pipeline (BE-07) sets
    # 'voice' + duration_ms when it persists a spoken turn. The IN ('text',
    # 'voice') CHECK is enforced server-side in the migration.
    origin = Column(
        String(10),
        nullable=False,
        default="text",
        server_default=text("'text'"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    #: Apagada por quem a escreveu. **Marca-se, não se remove.**
    #:
    #: Uma resposta da IA aponta para a pergunta que a gerou
    #: (`parent_message_id`), e há reacções, fixações e widgets pendurados
    #: nas mensagens: apagar a linha parte o fio. Marcá-la tira-a de todas as
    #: vistas e deixa o histórico para quem tiver de o auditar.
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    #: Editada, e **vê-se que foi**.
    #:
    #: Uma mensagem que muda de texto sem dizer que mudou é pior do que uma
    #: com um erro: numa conversa partilhada, alguém respondeu à versão
    #: anterior.
    edited_at = Column(DateTime(timezone=True), nullable=True)

    pinned_widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Threading + AI-bundling (chat-threads-master-plan PR1, 2026-05-20).
    # parent_message_id: a reply to a comment points at the comment;
    # an ai_response points at the triggering question.
    # incorporated_in_message_id: when a comment was bundled into an
    # Ask-AI call, set to the resulting ai_response id; FE renders
    # "incorporated in AI response #N" badges from this.
    parent_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    incorporated_in_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    # O achado que esta mensagem apresenta.
    #
    # A resposta diaria de um agente e uma mensagem do fio, mas no ecra tem de
    # ser o mesmo cartao do feed de Insights — grafico, indicadores, explicacao.
    # Esse conteudo vive em `agent_findings`; isto e o que diz ao cliente qual
    # achado corresponde a qual mensagem. NULL em tudo o resto.
    finding_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_findings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ── Uma mensagem de estado que não se repete ────────────────────
    #
    # Um agente corre de hora a hora. Quando não encontra nada, diz-o —
    # e tem de o dizer, porque o silêncio não se distingue de uma
    # avaria (ver a nota longa no `agent_worker`). Mas dizê-lo trinta
    # vezes seguidas enche o fio:
    #
    # > «temos muitas mensagens dessas repetidas… Está feio e isso
    # >  precisa arrumar» — Lucas, 06/10/2026
    #
    # Em vez de uma mensagem por corrida, a mesma mensagem conta as
    # corridas. O `created_at` diz desde quando, o
    # `ultima_repeticao_em` diz até quando, e o número diz quantas.
    # Nenhuma informação se perde — e a repetição passa a ser legível,
    # que é mais do que era: trinta cartões iguais escondem o facto de
    # serem trinta.
    #
    # Uma mensagem normal vale 1 e nunca muda.
    repeticoes = Column(
        Integer,
        nullable=False,
        server_default="1",
        default=1,
    )
    ultima_repeticao_em = Column(DateTime(timezone=True), nullable=True)
    # A entrada do catálogo (`src/core/locale.py`) que originou o texto.
    #
    # O `content` continua a ser escrito e é o que se vê sem isto. Mas
    # quem escreve é o worker, que corre sozinho e não sabe quem vai
    # ler: o mesmo agente é lido pelo Lucas em português e por um
    # cliente em castelhano. A chave deixa o cliente escolher a língua
    # na altura de mostrar, que é a única altura em que ela se sabe.
    chave_de_texto = Column(String(64), nullable=True)

    # Slack-style emoji reactions. Shape: {"👍": ["uuid", …], "❤️": [...]}.
    # Postgres → JSONB (indexable, efficient updates). SQLite (tests) →
    # plain JSON. The variant keeps the ORM portable while the prod
    # column stays JSONB via the migration. Default {} makes reads
    # None-safe across both dialects.
    reactions = Column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        server_default=text("'{}'"),
        default=dict,
    )

    # Transient (NON-mapped) author display name. Populated by the
    # message service from ``user_id`` so MessageResponse can serialise
    # the real author's name to collaborators. Defaults to None at the
    # class level so ``MessageResponse.model_validate(msg)`` never hits a
    # missing attribute for AI/system rows or paths that don't resolve it.
    author_name = None

    # Relationships — the `foreign_keys` disambiguates against the
    # parent_message_id / incorporated_in_message_id self-FKs added in
    # chat-threads PR1 (otherwise SQLAlchemy can't infer which FK pairs
    # parent ↔ child for the messages collection).
    conversation = relationship(
        "Conversation",
        back_populates="messages",
        foreign_keys=[conversation_id],
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_messages_role_valid",
        ),
        CheckConstraint(
            "kind IS NULL OR kind IN ('question', 'ai_response', 'comment', 'system')",
            name="ck_messages_kind_valid",
        ),
        Index(
            "idx_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, conv={self.conversation_id}, role={self.role})>"
