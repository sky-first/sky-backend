"""Domínios de email por cliente — descoberta de tenant no mobile.

O problema que isto resolve: na web o cliente vem do sub-domínio
(``workspace-gbtsolutions.skyfirstlabs.com``). Uma app móvel fala com um
único host e não tem sub-domínio nenhum, portanto quando alguém escreve
email e password o backend **não sabe em que base de dados procurar essa
pessoa** — os utilizadores vivem em bases separadas por cliente.

A resposta é o domínio do email, que é como o Microsoft Entra ID faz
(*home realm discovery*): ``lucas@gbtsolutions.pt`` → o domínio está
registado à GBT → autentica contra a base da GBT.

**Vários domínios por cliente**, de propósito. Empresas fundem-se,
compram outras e mudam de marca sem migrar o email de toda a gente. Um
domínio por cliente parecia suficiente até ao primeiro cliente com dois,
e nessa altura já é tarde.

O que **não** existe aqui, deliberadamente: um índice de emails
individuais. O Slack tem um, e é o que lhe permite o ecrã "encontra os
teus workspaces" — mas é uma tabela de dados pessoais partilhada entre
clientes, e a Sky não precisa dela. Um domínio diz "a GBT é cliente";
um email diria "o Lucas trabalha na GBT". A primeira é informação
comercial, a segunda é dado pessoal.

Quem não tiver email de um domínio registado não entra pelo mobile. É
uma decisão de produto, não uma limitação: a app é para funcionários de
clientes, criados por um administrador, e um email pessoal num login
corporativo é mais provavelmente um engano do que um caso legítimo.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


def normalize_domain(raw: str) -> str:
    """Forma canónica de um domínio.

    Minúsculas e sem o ponto final absoluto (``gbt.pt.``), que é válido
    em DNS e chegaria aqui como um domínio diferente do mesmo sítio.
    """
    return (raw or "").strip().lower().rstrip(".")


def domain_of_email(email: str) -> str:
    """A parte do domínio de um email, ou string vazia se não houver.

    Não valida o email — isso é do Pydantic. Só parte no último ``@``,
    porque a parte local pode legalmente conter um (entre aspas).
    """
    if not email or "@" not in email:
        return ""
    return normalize_domain(email.rsplit("@", 1)[1])


class TenantDomain(Base):
    """Um domínio de email que pertence a um cliente.

    Vive na base de dados de registo (a partilhada), não na do cliente —
    tem de ser consultável **antes** de sabermos qual é o cliente, que é
    precisamente o problema.
    """

    __tablename__ = "tenant_domains"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Único globalmente: um domínio não pode pertencer a dois clientes,
    # senão a resolução deixa de ser determinista e alguém entra na
    # empresa errada. A base impõe-o para não depender de disciplina.
    domain = Column(String(253), nullable=False, unique=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Desactivar em vez de apagar: um domínio retirado a um cliente não
    # deve poder ser reclamado por outro sem alguém decidir isso.
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("idx_tenant_domains_tenant", "tenant_id"),)

    def __repr__(self) -> str:
        return f"<TenantDomain {self.domain} → {self.tenant_id}>"


__all__ = ["TenantDomain", "domain_of_email", "normalize_domain"]
