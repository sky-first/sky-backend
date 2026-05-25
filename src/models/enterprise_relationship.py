"""Enterprise Relationship models.

Knowledge refactor Phase 6 extends the existing 1-to-many shape
(``sources`` JSON list + single ``target_id``) into full N↔N: a
``targets`` array, an optional multi-key ``keys`` array (e.g. join
master-users by email primary, name secondary, IBAN tertiary), an
``ai_inferred`` flag plus a ``confidence`` score, and the same
4-scope ACL columns the rest of the Knowledge model uses.

Existing single-target columns stay so Phase 5 callers keep working;
Phase 6 service layer prefers ``targets`` when populated.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.config.database import Base


_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class EnterpriseRelationship(Base):
    """Enterprise Relationship model — Phase 6 N↔N capable."""

    __tablename__ = "user_enterprise_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # ─── 1-to-many fan-out (legacy) ───────────────────────────────────
    # sources: list of {id: string, type: string}
    sources = Column(JSON, nullable=False)

    # Single-target legacy columns kept so existing callers don't break.
    # Phase 6 service prefers ``targets`` when populated.
    target_id = Column(String(255), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_details = Column(JSON, nullable=True)

    relationship_type = Column(String(50), nullable=False)

    # ─── Phase 6 N↔N ───────────────────────────────────────────────────
    # targets: list of {id, type, weight?} — when empty, fall back to
    # the single-target columns above. ``weight`` is the per-pair
    # confidence the AI uses to rank a match in multi-key joins.
    targets = Column(_JSONB_OR_JSON, nullable=False, default=list, server_default="[]")
    # keys: ordered list of {primary?, secondary?, tertiary?} entries
    # describing which columns join which side. Optional — joins that
    # don't need it leave the array empty.
    keys = Column(_JSONB_OR_JSON, nullable=False, default=list, server_default="[]")

    ai_inferred = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    confidence = Column(Numeric, nullable=True)

    # 4-scope ACL — same lattice as Metric / GlossaryTerm.
    scope = Column(String(20), nullable=True, index=True)
    scope_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return f"<EnterpriseRelationship(id={self.id}, name={self.name})>"
