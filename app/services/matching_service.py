"""匹配服务 — 向量召回 + A2A 精排 pipeline

 Pipeline: pgvector 向量召回 → 地点/硬过滤/黑名单 →
Top3 A2A 精排 → 匹配决策。
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event, MatchLog, MatchBlocklist
from app.models.chat import ChatRoom, ChatRoomMember
from app.models.user import Agent, User
from app.api.ws import manager as ws_manager
from app.services.a2a_matcher import a2a_matcher
from app.services.embedding_service import embedding_service
from app.services.match_blocklist_service import add_match_blocklist
from app.services.matching_policy import (
    A2AEvaluation,
    A2A_MATCH_THRESHOLD,
    Candidate,
    VECTOR_MATCH_THRESHOLD,
    adjusted_candidate_score,
    build_candidate_windows,
    choose_a2a_winner,
    collect_blocked_event_ids,
    has_time_overlap,
    is_age_filter_compatible,
    is_event_open_for_matching,
    is_gender_filter_compatible,
)
from app.services.location_policy import is_location_compatible
from app.services.push_notification_service import push_notification_service

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = VECTOR_MATCH_THRESHOLD
SEARCH_K = 30           # 向量搜索 top-k，为 Top3 A2A 保留足够候选


class MatchingService:
    def __init__(self, evaluator=a2a_matcher):
        self.evaluator = evaluator

    async def match_event(self, event_id: UUID, db: AsyncSession) -> dict | None:
        """主入口：对单个事件执行匹配"""
        result = await db.execute(
            select(Event).where(Event.id == event_id).with_for_update()
        )
        event = result.scalar_one_or_none()
        if not event or event.status != "pending":
            return None
        if not is_event_open_for_matching(
            start_time=event.start_time,
            expires_at=event.expires_at,
            now=datetime.now(timezone.utc),
        ):
            event.status = "cancelled"
            return None

        event.status = "matching"
        await db.flush()

        try:
            # 确保 embedding 存在
            await self._ensure_embedding(event)
            if event.embedding is None:
                logger.warning(f"Event {event_id} has no embedding, skip matching")
                event.status = "pending"
                return None

            # 向量搜索
            candidates = await self._vector_search(event, db, k=SEARCH_K)
            if not candidates:
                event.status = "pending"
                event.match_round += 1
                return None

            # 硬过滤 + Top3 候选窗口
            filtered = await self._post_filter(event, candidates, db)
            if not filtered:
                event.status = "pending"
                event.match_round += 1
                return None

            blocked_event_ids = await self._blocked_event_ids(event, db)
            candidate_by_id = {candidate.id: candidate for candidate, _ in filtered}
            candidate_scores = [
                Candidate(event_id=candidate.id, vector_score=score)
                for candidate, score in filtered
            ]
            windows = build_candidate_windows(
                candidate_scores,
                blocked_event_ids=blocked_event_ids,
                vector_threshold=MATCH_THRESHOLD,
            )
            if not windows:
                event.status = "pending"
                event.match_round += 1
                for cand, score in filtered[:3]:
                    db.add(MatchLog(
                        event_a_id=event.id, event_b_id=cand.id,
                        stage="vector_search", score=score,
                        result="rejected",
                    ))
                return None

            all_evaluations = []
            for round_index, window in enumerate(windows, start=1):
                evaluations = []
                for candidate in window:
                    candidate_event = candidate_by_id.get(candidate.event_id)
                    if candidate_event is None:
                        continue
                    evaluation = await self.evaluator.evaluate(event, candidate_event, db)
                    evaluations.append(evaluation)
                    all_evaluations.append(evaluation)
                    db.add(MatchLog(
                        event_a_id=event.id,
                        event_b_id=candidate_event.id,
                        stage=f"a2a_round_{round_index}",
                        score=evaluation.compatibility,
                        reasons=evaluation.reasons,
                        issues=evaluation.issues,
                        score_breakdown=evaluation.score_breakdown,
                        dialogue_log=evaluation.dialogue_log,
                        result="accepted" if evaluation.should_match else "rejected",
                    ))

                winner = choose_a2a_winner(evaluations)
                if not winner:
                    continue

                matched = await self._try_commit_a2a_winner(event, winner, evaluations, db)
                if matched:
                    return matched

            if all_evaluations:
                await self._blocklist_evaluated_pairs(event, all_evaluations, db)
            event.status = "pending"
            event.match_round += 1
            return None

        except Exception as e:
            logger.error(f"Matching failed for event {event_id}: {e}")
            event.status = "pending"
            raise

    async def _ensure_embedding(self, event: Event):
        """确保事件有 embedding；地点语义只从 location 进入匹配。"""
        if event.embedding is None:
            text = embedding_service.build_event_text(
                event.title, event.activity_type, None,
                event.location, event.preferences, event.constraints
            )
            event.embedding = await embedding_service.encode(text)

    async def _vector_search(self, event: Event, db: AsyncSession,
                             k: int = 20) -> list[tuple[Event, float]]:
        """pgvector 向量搜索：宽召回 + cosine distance 排序"""
        filters = [
            Event.id != event.id,
            Event.user_id != event.user_id,
            Event.status == "pending",
            Event.embedding.is_not(None),
            or_(Event.expires_at.is_(None), Event.expires_at > datetime.now(timezone.utc)),
            or_(Event.start_time.is_(None), Event.start_time > datetime.now(timezone.utc)),
        ]

        # 地点语义只在 _post_filter 中从 location 判断。
        # 这里保持宽召回，避免「川西」「江浙沪」「东京周边」这类区域表达被 SQL 阶段误杀。

        query = (
            select(Event, Event.embedding.cosine_distance(event.embedding).label("distance"))
            .where(*filters)
            .order_by("distance")
            .limit(k)
        )

        result = await db.execute(query)
        rows = result.all()

        # cosine similarity = 1 - cosine distance
        return [(row[0], 1.0 - row[1]) for row in rows]

    async def _post_filter(
        self,
        event: Event,
        candidates: list[tuple[Event, float]],
        db: AsyncSession,
    ) -> list[tuple[Event, float]]:
        """硬过滤：时间交集检查，不在这里截断 Top3。"""
        profiles = await self._user_profiles_for_events(
            event,
            [candidate for candidate, _ in candidates],
            db,
        )
        today = datetime.now(timezone.utc).date()
        filtered = []
        for cand, score in candidates:
            source_profile = profiles.get(event.user_id, {})
            candidate_profile = profiles.get(cand.user_id, {})
            if not has_time_overlap(event, cand):
                continue
            if not is_location_compatible(event, cand).should_pass:
                continue
            age_decision = is_age_filter_compatible(
                source_event=event,
                source_birth_date=source_profile.get("birth_date"),
                candidate_event=cand,
                candidate_birth_date=candidate_profile.get("birth_date"),
                today=today,
            )
            if not age_decision.should_pass:
                continue
            gender_decision = is_gender_filter_compatible(
                source_event=event,
                source_gender=source_profile.get("gender"),
                candidate_event=cand,
                candidate_gender=candidate_profile.get("gender"),
            )
            if not gender_decision.should_pass:
                continue
            filtered.append((cand, adjusted_candidate_score(score, age_decision, gender_decision)))

        filtered.sort(key=lambda item: item[1], reverse=True)
        return filtered

    async def _user_profiles_for_events(
        self,
        event: Event,
        candidates: list[Event],
        db: AsyncSession,
    ) -> dict[UUID, dict]:
        user_ids = {event.user_id}
        user_ids.update(candidate.user_id for candidate in candidates)
        result = await db.execute(
            select(User.id, User.birth_date, User.gender).where(User.id.in_(user_ids))
        )
        return {
            row[0]: {
                "birth_date": row[1],
                "gender": row[2],
            }
            for row in result.all()
        }

    async def _blocked_event_ids(
        self,
        event: Event,
        db: AsyncSession,
    ) -> set[UUID]:
        result = await db.execute(
            select(MatchBlocklist).where(
                or_(
                    MatchBlocklist.event_a_id == event.id,
                    MatchBlocklist.event_b_id == event.id,
                )
            )
        )
        return collect_blocked_event_ids(
            source_event_id=event.id,
            blocklist_rows=result.scalars().all(),
        )

    async def _try_commit_a2a_winner(
        self,
        event: Event,
        winner: A2AEvaluation,
        evaluations: list[A2AEvaluation],
        db: AsyncSession,
    ) -> dict | None:
        accepted = sorted(
            [
                evaluation for evaluation in evaluations
                if evaluation.should_match and evaluation.compatibility >= A2A_MATCH_THRESHOLD
            ],
            key=lambda evaluation: evaluation.compatibility,
            reverse=True,
        )
        if winner not in accepted:
            accepted.insert(0, winner)

        for evaluation in accepted:
            best_result = await db.execute(
                select(Event)
                .where(Event.id == evaluation.candidate_event_id)
                .with_for_update(skip_locked=True)
            )
            best_event = best_result.scalar_one_or_none()
            if not best_event or best_event.status != "pending":
                continue

            event.status = "matched"
            event.matched_event_id = best_event.id
            event.match_score = evaluation.compatibility

            best_event.status = "matched"
            best_event.matched_event_id = event.id
            best_event.match_score = evaluation.compatibility

            db.add(MatchLog(
                event_a_id=event.id,
                event_b_id=best_event.id,
                stage="final",
                score=evaluation.compatibility,
                reasons=evaluation.reasons,
                issues=evaluation.issues,
                score_breakdown=evaluation.score_breakdown,
                dialogue_log=evaluation.dialogue_log,
                result="accepted",
            ))

            chat_room_id = await self._create_chat_room(
                event,
                best_event,
                evaluation.summary,
                evaluation.dialogue_log,
                db,
            )

            return {
                "matched_event_id": str(best_event.id),
                "score": evaluation.compatibility,
                "reasons": evaluation.reasons or [evaluation.summary],
                "chat_room_id": str(chat_room_id),
            }

        return None

    async def _blocklist_evaluated_pairs(
        self,
        event: Event,
        evaluations: list[A2AEvaluation],
        db: AsyncSession,
    ) -> None:
        for evaluation in evaluations:
            candidate = await db.get(Event, evaluation.candidate_event_id)
            if candidate is None:
                continue
            await add_match_blocklist(
                db,
                user_a_id=event.user_id,
                user_b_id=candidate.user_id,
                event_a_id=event.id,
                event_b_id=candidate.id,
                reason="a2a_rejected",
            )

    async def force_match(self, event_id_a: UUID, event_id_b: UUID,
                          db: AsyncSession) -> dict:
        """手动匹配：不受阈值限制"""
        result_a = await db.execute(select(Event).where(Event.id == event_id_a))
        result_b = await db.execute(select(Event).where(Event.id == event_id_b))
        event_a = result_a.scalar_one_or_none()
        event_b = result_b.scalar_one_or_none()

        if not event_a or not event_b:
            raise ValueError("事件不存在")
        if event_a.user_id == event_b.user_id:
            raise ValueError("不能匹配同一用户的事件")

        # 确保双方有 embedding
        await self._ensure_embedding(event_a)
        await self._ensure_embedding(event_b)

        # 计算向量相似度（通过 pgvector ORM）
        score = 0.0
        if event_a.embedding is not None and event_b.embedding is not None:
            dist_result = await db.execute(
                select(Event.embedding.cosine_distance(event_a.embedding).label("dist"))
                .where(Event.id == event_b.id)
            )
            dist = dist_result.scalar()
            score = 1.0 - dist if dist is not None else 0.0

        # 强制匹配
        event_a.status = "matched"
        event_a.matched_event_id = event_b.id
        event_a.match_score = score

        event_b.status = "matched"
        event_b.matched_event_id = event_a.id
        event_b.match_score = score

        db.add(MatchLog(
            event_a_id=event_a.id, event_b_id=event_b.id,
            stage="manual_vector", score=score,
            result="force_matched",
        ))

        chat_room_id = await self._create_chat_room(
            event_a, event_b, f"手动匹配 (向量分数: {score:.2f})", None, db
        )

        return {
            "score": score,
            "chat_room_id": str(chat_room_id),
        }

    async def preview_match(self, event_id: UUID, db: AsyncSession) -> dict:
        """预览匹配候选（不执行匹配），返回全部召回事件及过滤详情"""
        result = await db.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            raise ValueError("事件不存在")

        await self._ensure_embedding(event)

        candidates = await self._vector_search(event, db, k=10)
        filtered = await self._post_filter(event, candidates, db)
        blocked_event_ids = await self._blocked_event_ids(event, db)
        profiles = await self._user_profiles_for_events(
            event,
            [candidate for candidate, _ in candidates],
            db,
        )
        detailed = self._post_filter_detailed(event, candidates, blocked_event_ids, profiles)
        matched_event = await self._matched_event_for_preview(event, db)

        return {
            "event": self._event_to_dict(event),
            "city_normalized": event.city_normalized,
            "threshold": MATCH_THRESHOLD,
            "matched_event": matched_event,
            "candidates": detailed,
            "total_recalled": len(candidates),
            "total_passed": sum(1 for c in detailed if c["passed"]),
        }

    async def _matched_event_for_preview(self, event: Event, db: AsyncSession) -> dict | None:
        if not event.matched_event_id:
            return None

        result = await db.execute(select(Event).where(Event.id == event.matched_event_id))
        matched_event = result.scalar_one_or_none()
        if not matched_event:
            return None

        pair_filter = or_(
            (MatchLog.event_a_id == event.id) & (MatchLog.event_b_id == matched_event.id),
            (MatchLog.event_a_id == matched_event.id) & (MatchLog.event_b_id == event.id),
        )
        log_result = await db.execute(
            select(MatchLog)
            .where(pair_filter)
            .order_by(MatchLog.created_at.desc())
            .limit(1)
        )
        latest_log = log_result.scalar_one_or_none()
        score = latest_log.score if latest_log else event.match_score

        return {
            "event": self._event_to_dict(matched_event),
            "similarity": round(float(score or 0), 4),
            "passed": True,
            "status": "matched_pair",
            "filter_reason": "当前已匹配",
            "reasons": latest_log.reasons if latest_log else [],
            "issues": latest_log.issues if latest_log else [],
        }

    def _post_filter_detailed(
        self,
        event: Event,
        candidates: list[tuple[Event, float]],
        blocked_event_ids: set[UUID],
        profiles: dict[UUID, dict],
    ) -> list[dict]:
        """后过滤并返回每个候选的详细状态"""
        results = []
        passed_count = 0
        today = datetime.now(timezone.utc).date()
        for cand, score in candidates:
            status = "passed"
            filter_reason = None
            source_profile = profiles.get(event.user_id, {})
            candidate_profile = profiles.get(cand.user_id, {})
            adjusted_score = score

            if not has_time_overlap(event, cand):
                status = "hard_filtered"
                filter_reason = f"时间无交集: 事件[{event.start_time.strftime('%m/%d %H:%M')}-{event.end_time.strftime('%m/%d %H:%M')}] vs 候选[{cand.start_time.strftime('%m/%d %H:%M')}-{cand.end_time.strftime('%m/%d %H:%M')}]"

            if status == "passed":
                location_decision = is_location_compatible(event, cand)
                if not location_decision.should_pass:
                    status = "location_filtered"
                    filter_reason = (
                        f"地点不兼容: {location_decision.relation}, "
                        f"score={location_decision.score:.2f} < {location_decision.threshold:.2f}"
                    )

            if status == "passed":
                age_decision = is_age_filter_compatible(
                    source_event=event,
                    source_birth_date=source_profile.get("birth_date"),
                    candidate_event=cand,
                    candidate_birth_date=candidate_profile.get("birth_date"),
                    today=today,
                )
                if not age_decision.should_pass:
                    status = "age_filtered"
                    filter_reason = "；".join(age_decision.issues) or "年龄条件不兼容"

            if status == "passed":
                gender_decision = is_gender_filter_compatible(
                    source_event=event,
                    source_gender=source_profile.get("gender"),
                    candidate_event=cand,
                    candidate_gender=candidate_profile.get("gender"),
                )
                if not gender_decision.should_pass:
                    status = "gender_filtered"
                    filter_reason = "；".join(gender_decision.issues) or "性别条件不兼容"
                else:
                    adjusted_score = adjusted_candidate_score(score, age_decision, gender_decision)

            if status == "passed" and cand.id in blocked_event_ids:
                status = "blocklisted"
                filter_reason = "命中事件对黑名单"

            # 阈值检查
            if status == "passed" and adjusted_score < MATCH_THRESHOLD:
                status = "below_threshold"
                filter_reason = f"相似度 {adjusted_score:.4f} < 阈值 {MATCH_THRESHOLD}"

            if status == "passed":
                passed_count += 1
                if passed_count <= 3:
                    status = "a2a_round_1"
                    filter_reason = "进入 Top3 A2A 精排"
                else:
                    status = "standby"
                    filter_reason = "超过 Top3 A2A 候选窗口，暂不评估"

            results.append({
                "event": self._event_to_dict(cand),
                "similarity": round(adjusted_score, 4),
                "passed": status == "a2a_round_1",
                "status": status,
                "filter_reason": filter_reason,
            })

        return results

    @staticmethod
    def _event_to_dict(event: Event) -> dict:
        return {
            "id": str(event.id),
            "title": event.title,
            "activity_type": event.activity_type,
            "city": event.city,
            "city_normalized": event.city_normalized,
            "location": event.location,
            "start_time": event.start_time.isoformat() if event.start_time else None,
            "end_time": event.end_time.isoformat() if event.end_time else None,
            "preferences": event.preferences or [],
            "constraints": event.constraints or [],
            "status": event.status,
            "user_id": str(event.user_id),
        }

    async def _create_chat_room(self, event_a: Event, event_b: Event,
                                match_summary: str, agent_dialogue: str | None,
                                db: AsyncSession) -> uuid.UUID:
        """创建聊天室 + 添加成员"""
        room = ChatRoom(
            event_id_a=event_a.id,
            event_id_b=event_b.id,
            match_summary=match_summary,
            agent_dialogue=agent_dialogue,
        )
        db.add(room)
        await db.flush()

        # 添加两个用户为成员（event_a 的用户为 owner）
        for uid, is_owner in [(event_a.user_id, True), (event_b.user_id, False)]:
            db.add(ChatRoomMember(
                room_id=room.id,
                user_id=uid,
                role="user",
                is_owner=is_owner,
            ))

        # 添加两个 Agent 为成员
        for user_id in [event_a.user_id, event_b.user_id]:
            agent_result = await db.execute(
                select(Agent).where(Agent.user_id == user_id)
            )
            agent = agent_result.scalar_one_or_none()
            if agent:
                db.add(ChatRoomMember(
                    room_id=room.id,
                    user_id=user_id,       # agent 所属用户的 ID
                    agent_id=agent.id,     # agent 自己的 ID
                    role="agent",
                ))

        # WebSocket 通知双方用户匹配成功
        for uid, eid in [(event_a.user_id, event_a.id), (event_b.user_id, event_b.id)]:
            await ws_manager.send_to_user(str(uid), {
                "type": "event_update",
                "event_id": str(eid),
                "status": "matched",
            })
            await ws_manager.send_to_user(str(uid), {
                "type": "room_created",
                "room_id": str(room.id),
            })

        try:
            await push_notification_service.send_to_users(
                db,
                [event_a.user_id, event_b.user_id],
                title="匹配成功，聊天室已创建",
                body="新的搭子聊天室已开启，去打个招呼吧。",
                data={
                    "type": "room_created",
                    "room_id": str(room.id),
                },
            )
        except Exception as exc:
            logger.warning("Room created but push notification failed: %s", exc)

        return room.id


matching_service = MatchingService()
