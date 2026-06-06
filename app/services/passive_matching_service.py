"""被动匹配服务 — 只发邀请，用户确认后才创建聊天室。"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ws import manager as ws_manager
from app.models.chat import ChatMessage, ChatRoom, ChatRoomMember, PassiveMatchRequest
from app.models.event import Event
from app.models.user import Agent, User
from app.services.location_policy import is_location_compatible
from app.services.match_blocklist_service import add_match_blocklist
from app.services.matching_policy import (
    adjusted_candidate_score,
    is_age_filter_compatible,
    is_gender_filter_compatible,
)
from app.services.push_notification_service import push_notification_service

logger = logging.getLogger(__name__)

PASSIVE_MATCH_THRESHOLD = 2
CANDIDATE_TOP_K = 10
PASSIVE_VECTOR_THRESHOLD = 0.3
NO_AGE_FILTER_EVENT = SimpleNamespace(
    age_filter_min=None,
    age_filter_max=None,
    age_filter_mode=None,
)
NO_GENDER_FILTER_EVENT = SimpleNamespace(
    preferences=[],
    constraints=[],
)


class PassiveMatchingService:
    async def run_passive_matching(self, db: AsyncSession) -> int:
        """Scan eligible events and create passive match requests."""
        result = await db.execute(
            select(Event).where(
                Event.status == "pending",
                Event.match_round >= PASSIVE_MATCH_THRESHOLD,
                Event.embedding.is_not(None),
                or_(Event.expires_at.is_(None), Event.expires_at > datetime.now(timezone.utc)),
                or_(Event.start_time.is_(None), Event.start_time > datetime.now(timezone.utc)),
            )
        )
        events = result.scalars().all()
        logger.info(f"Passive matching: found {len(events)} eligible events")

        request_count = 0
        for event in events:
            try:
                success = await self._create_request_for_event(event, db)
                if success:
                    request_count += 1
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"Passive request failed for event {event.id}: {e}")

        return request_count

    async def _create_request_for_event(self, event: Event, db: AsyncSession) -> bool:
        existing = await db.execute(
            select(PassiveMatchRequest).where(
                PassiveMatchRequest.event_id == event.id,
                PassiveMatchRequest.status == "pending",
            )
        )
        if existing.scalar_one_or_none():
            return False

        params = {
            "event_id": str(event.id),
            "event_user_id": str(event.user_id),
            "embedding": event.embedding,
        }

        requester_r = await db.execute(select(User).where(User.id == event.user_id))
        requester = requester_r.scalar_one_or_none()

        query = text("""
            SELECT u.id, u.name, u.city, u.birth_date, u.gender, u.embedding <=> :embedding AS distance
            FROM users u
            WHERE u.id != :event_user_id
              AND u.is_active = TRUE
              AND u.embedding IS NOT NULL
              AND u.welcome_disturb = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM passive_match_requests pmr
                  WHERE pmr.event_id = :event_id
                    AND pmr.target_user_id = u.id
                    AND pmr.status = 'pending'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM match_blocklists mb
                  WHERE (mb.event_a_id = :event_id OR mb.event_b_id = :event_id)
                    AND (
                         (mb.user_a_id = :event_user_id AND mb.user_b_id = u.id)
                         OR (mb.user_b_id = :event_user_id AND mb.user_a_id = u.id)
                     )
              )
            ORDER BY distance ASC
            LIMIT :limit
        """)
        params["limit"] = CANDIDATE_TOP_K

        result = await db.execute(query, params)
        candidates = []
        today = datetime.now(timezone.utc).date()
        for row in result.all():
            similarity = 1.0 - row[5]
            if not is_location_compatible(
                event,
                {"activity_type": event.activity_type, "city": row[2], "location": row[2]},
            ).should_pass:
                continue
            age_decision = is_age_filter_compatible(
                source_event=event,
                source_birth_date=None,
                candidate_event=NO_AGE_FILTER_EVENT,
                candidate_birth_date=row[3],
                today=today,
            )
            if not age_decision.should_pass:
                continue
            gender_decision = is_gender_filter_compatible(
                source_event=event,
                source_gender=requester.gender if requester else None,
                candidate_event=NO_GENDER_FILTER_EVENT,
                candidate_gender=row[4],
            )
            if not gender_decision.should_pass:
                continue
            adjusted_similarity = adjusted_candidate_score(similarity, age_decision, gender_decision)
            if adjusted_similarity < PASSIVE_VECTOR_THRESHOLD:
                continue
            candidates.append((row, adjusted_similarity))
        if not candidates:
            logger.info(f"No passive candidates for event {event.id}")
            return False

        candidates.sort(key=lambda item: item[1], reverse=True)
        chosen, similarity = candidates[0]
        chosen_user_id = chosen[0]
        target_name = chosen[1]

        message = (
            f"{requester.name if requester else '有人'} 想约「{event.title}」。"
            "如果你有兴趣，确认后会创建聊天室。"
        )
        request = PassiveMatchRequest(
            event_id=event.id,
            requester_user_id=event.user_id,
            target_user_id=chosen_user_id,
            similarity=similarity,
            message=message,
        )
        db.add(request)
        await db.flush()

        logger.info(
            f"Passive request: event {event.id} -> user {target_name} "
            f"(similarity={similarity:.3f})"
        )
        await ws_manager.send_to_user(str(chosen_user_id), {
            "type": "match_request_created",
            "request_id": str(request.id),
        })
        return True

    async def respond_to_request(
        self,
        request_id: UUID,
        user_id: UUID,
        action: str,
        db: AsyncSession,
    ) -> dict:
        result = await db.execute(
            select(PassiveMatchRequest)
            .where(PassiveMatchRequest.id == request_id)
            .with_for_update()
        )
        request = result.scalar_one_or_none()
        if not request or request.target_user_id != user_id:
            raise ValueError("请求不存在或无权操作")
        if request.status != "pending":
            raise ValueError(f"请求状态为 {request.status}，无法再次处理")

        action = action.lower()
        if action not in {"accept", "reject"}:
            raise ValueError("action 必须是 accept 或 reject")

        request.responded_at = datetime.now(timezone.utc)
        if action == "reject":
            request.status = "rejected"
            await add_match_blocklist(
                db,
                event_a_id=request.event_id,
                event_b_id=None,
                user_a_id=request.requester_user_id,
                user_b_id=request.target_user_id,
                reason="passive_rejected",
                source_request_id=request.id,
            )
            return {"status": "rejected"}

        event_r = await db.execute(
            select(Event)
            .where(Event.id == request.event_id)
            .with_for_update()
        )
        event = event_r.scalar_one_or_none()
        if not event or event.status != "pending":
            raise ValueError("活动已不可匹配")

        request.status = "accepted"
        event.status = "matched"
        room_id = await self._create_passive_room(event, request, db)
        await ws_manager.send_to_user(str(request.requester_user_id), {
            "type": "event_update",
            "event_id": str(event.id),
            "status": "matched",
        })
        for uid in [request.requester_user_id, request.target_user_id]:
            await ws_manager.send_to_user(str(uid), {
                "type": "room_created",
                "room_id": str(room_id),
            })
        try:
            await push_notification_service.send_to_users(
                db,
                [request.requester_user_id, request.target_user_id],
                title="聊天室已创建",
                body="被动邀请已确认，新的搭子聊天室已开启。",
                data={
                    "type": "room_created",
                    "room_id": str(room_id),
                },
            )
        except Exception as exc:
            logger.warning("Passive room created but push notification failed: %s", exc)
        return {"status": "accepted", "room_id": str(room_id)}

    async def _create_passive_room(
        self,
        event: Event,
        request: PassiveMatchRequest,
        db: AsyncSession,
    ) -> uuid.UUID:
        room = ChatRoom(
            event_id_a=event.id,
            event_id_b=None,
            match_summary=f"被动邀请已确认，相似度: {(request.similarity or 0):.2f}",
            match_type="passive",
        )
        db.add(room)
        await db.flush()

        for uid, is_owner in [(request.requester_user_id, True), (request.target_user_id, False)]:
            db.add(ChatRoomMember(
                room_id=room.id,
                user_id=uid,
                role="user",
                is_owner=is_owner,
            ))

        for uid in [request.requester_user_id, request.target_user_id]:
            agent_r = await db.execute(select(Agent).where(Agent.user_id == uid))
            agent = agent_r.scalar_one_or_none()
            if agent:
                db.add(ChatRoomMember(
                    room_id=room.id,
                    user_id=uid,
                    agent_id=agent.id,
                    role="agent",
                ))

        welcome_msg = ChatMessage(
            room_id=room.id,
            sender_id=request.requester_user_id,
            sender_type="system",
            content="你们已确认这次被动邀请。先聊聊时间、地点和偏好，合适的话再投「搭」。",
        )
        db.add(welcome_msg)
        await db.flush()
        return room.id


passive_matching_service = PassiveMatchingService()
