"""Um convite para um projeto — enquanto a pessoa não responde.

> *"Enviamos um convite à pessoa, esta recebe uma notificação e aceita o
> projeto, e nós recebemos uma notificação que a pessoa aceitou."*
> — Lucas, 26/08/2026

**Porque é preciso uma tabela e não bastava acrescentar a pessoa logo.**
Porque "aceitar" tem de querer dizer alguma coisa. Se convidar já desse
acesso, o botão de aceitar era decoração e o de recusar era uma mentira — a
pessoa já teria estado lá dentro. E este projeto liga-se a dados reais: o
acesso aos números de uma área não deve nascer do gesto de uma pessoa
sozinha, sem que a outra sequer saiba.

Enquanto o convite está `pendente` a pessoa **não** alcança o projeto. Só ao
aceitar é que entra — pela equipa Geral, como qualquer outra pessoa
convidada à unidade.
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class ConviteAoProjeto(Base):
    """Convite pendente, aceite ou recusado."""

    __tablename__ = "convites_ao_projeto"
    __table_args__ = (
        # Um convite vivo de cada vez por pessoa e projeto. Convites
        # respondidos ficam guardados — quem recusou pode ser convidado outra
        # vez — por isso a chave inclui o estado.
        UniqueConstraint("space_id", "user_id", "estado", name="uq_convite_vivo"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(
        UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Que papel terá quando aceitar — owner, editor, viewer.
    papel = Column(String(20), nullable=False, default="editor")
    estado = Column(String(20), nullable=False, default="pendente")  # pendente|aceite|recusado
    convidado_por = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    respondido_em = Column(DateTime(timezone=True), nullable=True)
