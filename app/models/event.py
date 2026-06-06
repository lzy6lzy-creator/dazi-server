from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Boolean, Text, ARRAY, TIMESTAMP, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    activity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    start_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    location: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(50), index=True)
    preferences: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)
    constraints: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)
    clarification_answers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    age_filter_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_filter_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_filter_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending -> matching -> matched -> active -> completed -> cancelled
    matched_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    match_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    match_round: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(Vector(768), nullable=True)
    city_normalized: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)


class MatchLog(Base):
    """匹配日志 - 记录每次匹配过程"""
    __tablename__ = "match_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_a_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    event_b_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)  # coarse_rank / a2a_dialogue / final
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    issues: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    score_breakdown: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dialogue_log: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(20), default="pending")  # pending / accepted / rejected
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))


class MatchBlocklist(Base):
    """Pairs that should not be matched again after rejection or declined invite."""
    __tablename__ = "match_blocklists"
    __table_args__ = (
        Index("ix_match_blocklists_event_pair", "event_a_id", "event_b_id"),
        Index("ix_match_blocklists_user_pair", "user_a_id", "user_b_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_a_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_b_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_a_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_b_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(40), default="rejected")
    source_room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
