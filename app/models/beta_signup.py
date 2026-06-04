from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import ARRAY, Index, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BetaSignup(Base):
    """Homepage TestFlight beta signup."""

    __tablename__ = "beta_signups"
    __table_args__ = (
        Index("ix_beta_signups_email_created", "email", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    contact: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    device: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activity_interests: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="homepage")
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
