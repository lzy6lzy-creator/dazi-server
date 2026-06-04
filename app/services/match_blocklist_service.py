from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import MatchBlocklist
from app.services.matching_policy import canonical_pair_id


async def add_match_blocklist(
    db: AsyncSession,
    *,
    user_a_id: UUID,
    user_b_id: UUID,
    event_a_id: UUID | None = None,
    event_b_id: UUID | None = None,
    reason: str = "rejected",
    source_room_id: UUID | None = None,
    source_request_id: UUID | None = None,
) -> MatchBlocklist:
    user_a_id, user_b_id = canonical_pair_id(user_a_id, user_b_id)
    if event_a_id and event_b_id:
        event_a_id, event_b_id = canonical_pair_id(event_a_id, event_b_id)

    existing = await db.execute(
        select(MatchBlocklist).where(
            MatchBlocklist.user_a_id == user_a_id,
            MatchBlocklist.user_b_id == user_b_id,
            MatchBlocklist.event_a_id == event_a_id,
            (
                MatchBlocklist.event_b_id.is_(None)
                if event_b_id is None
                else MatchBlocklist.event_b_id == event_b_id
            ),
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        return row

    row = MatchBlocklist(
        event_a_id=event_a_id,
        event_b_id=event_b_id,
        user_a_id=user_a_id,
        user_b_id=user_b_id,
        reason=reason,
        source_room_id=source_room_id,
        source_request_id=source_request_id,
    )
    db.add(row)
    await db.flush()
    return row
