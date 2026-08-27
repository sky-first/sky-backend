"""Apagar e editar uma mensagem.

> *"Não dá para apagar uma mensagem (perguntou no projeto errado)."*
> *"Não dá para editar e reenviar (erro de escrita)."* — Lucas, itens 4.3 e 4.4

**Porque é apagar a sério e não esconder.** A razão que o Lucas deu para
querer apagar não é vergonha de uma pergunta: é ter perguntado **no projeto
errado**. E uma pergunta feita no projeto errado traz uma resposta com dados
desse projeto. Deixar a resposta e apagar só a pergunta era deixar o que
interessa.

**Porque é `deleted_at` e não `DELETE`.** Uma resposta da IA aponta para a
pergunta que a gerou (`parent_message_id`), e há reacções, fixações e widgets
pendurados nas mensagens. Apagar a linha parte o fio; marcá-la tira-a de todas
as vistas e deixa o histórico inteiro para quem tiver de o auditar.

**`edited_at` é para se ver.** Uma mensagem que muda de texto sem dizer que
mudou é pior do que uma com um erro: numa conversa partilhada, alguém
respondeu à versão anterior.

Revision ID: apagar_e_editar_mensagem_20260826
Revises: convite_ao_projeto_20260826
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision = "apagar_e_editar_mensagem_20260826"
down_revision = "convite_ao_projeto_20260826"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    # As listagens filtram por `deleted_at IS NULL` em cada conversa; sem
    # índice isso é uma leitura completa da tabela a cada abertura de chat.
    op.create_index(
        "idx_messages_conversa_vivas",
        "messages",
        ["conversation_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_messages_conversa_vivas", table_name="messages")
    op.drop_column("messages", "edited_at")
    op.drop_column("messages", "deleted_at")
