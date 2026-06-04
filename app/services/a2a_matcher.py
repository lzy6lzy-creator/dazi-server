from __future__ import annotations

import logging
from uuid import UUID

from app.services.matching_policy import A2AEvaluation, A2A_MATCH_THRESHOLD

logger = logging.getLogger(__name__)


def parse_a2a_response(
    source_event_id: UUID,
    candidate_event_id: UUID,
    payload,
) -> A2AEvaluation:
    if not isinstance(payload, dict):
        return A2AEvaluation(
            source_event_id=source_event_id,
            candidate_event_id=candidate_event_id,
            compatibility=0.0,
            should_match=False,
            summary="A2A 评估失败",
            issues=["LLM 未返回可解析 JSON"],
        )

    compatibility = _safe_float(payload.get("compatibility"))
    dialogue_log = _format_dialogue(payload.get("dialogue"))
    reasons = _string_list(payload.get("match_reasons"))
    issues = _string_list(payload.get("potential_issues"))
    summary = str(payload.get("summary") or "A2A 未给出摘要")

    return A2AEvaluation(
        source_event_id=source_event_id,
        candidate_event_id=candidate_event_id,
        compatibility=compatibility,
        should_match=compatibility >= A2A_MATCH_THRESHOLD,
        summary=summary,
        reasons=reasons,
        issues=issues,
        dialogue_log=dialogue_log,
    )


def _safe_float(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _format_dialogue(dialogue) -> str | None:
    if not isinstance(dialogue, list):
        return None
    lines = []
    for item in dialogue:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "Agent").strip()
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"{speaker}: {content}")
    return "\n".join(lines) if lines else None


class A2AMatcher:
    async def evaluate(self, source, candidate, db) -> A2AEvaluation:
        try:
            from app.services.llm_service import llm_service

            prompt = await self._build_prompt(source, candidate, db)
            payload = await llm_service.chat_json(
                [{"role": "system", "content": prompt}],
                temperature=0.3,
                max_tokens=2048,
            )
            return parse_a2a_response(source.id, candidate.id, payload)
        except Exception as e:
            logger.error(f"A2A evaluation failed for {source.id} -> {candidate.id}: {e}")
            return A2AEvaluation(
                source_event_id=source.id,
                candidate_event_id=candidate.id,
                compatibility=0.0,
                should_match=False,
                summary="A2A 评估失败",
                issues=[str(e)],
            )

    async def _build_prompt(self, source, candidate, db) -> str:
        from app.services.prompt_builder import PromptBuilder

        user_a = await self._get_user(source.user_id, db)
        user_b = await self._get_user(candidate.user_id, db)
        agent_a = await self._get_agent(source.user_id, db)
        agent_b = await self._get_agent(candidate.user_id, db)
        memories_a = await self._get_memories(source.user_id, db)
        memories_b = await self._get_memories(candidate.user_id, db)

        return PromptBuilder.build_a2a_dialogue_prompt(
            agent_a_name=agent_a.name if agent_a else "点点",
            agent_b_name=agent_b.name if agent_b else "点点",
            event_a=self._event_dict(source),
            event_b=self._event_dict(candidate),
            user_a_info=self._user_dict(user_a),
            user_b_info=self._user_dict(user_b),
            memories_a=memories_a,
            memories_b=memories_b,
        )

    async def _get_user(self, user_id: UUID, db):
        from sqlalchemy import select
        from app.models.user import User

        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def _get_agent(self, user_id: UUID, db):
        from sqlalchemy import select
        from app.models.user import Agent

        result = await db.execute(select(Agent).where(Agent.user_id == user_id))
        return result.scalar_one_or_none()

    async def _get_memories(self, user_id: UUID, db) -> list[tuple[str, str]]:
        from sqlalchemy import select
        from app.models.user import AgentMemory

        result = await db.execute(
            select(AgentMemory)
            .where(AgentMemory.user_id == user_id, AgentMemory.is_active == True)
            .order_by(AgentMemory.confidence.desc())
            .limit(10)
        )
        return [(m.type, m.content) for m in result.scalars().all()]

    @staticmethod
    def _event_dict(event) -> dict:
        from app.services.location_normalizer import normalize_place

        place = normalize_place(
            activity_type=event.activity_type,
            city=event.city,
            location=event.location,
        )
        location_profile = (
            f"{place.place_kind}/{place.place_normalized or 'unknown'}"
            f"/city={place.admin_city or '-'}"
            f"/region={place.admin_region or '-'}"
            f"/scope={place.geo_scope}"
        )
        return {
            "title": event.title,
            "activity_type": event.activity_type,
            "city": event.city,
            "start_time": event.start_time.isoformat() if event.start_time else None,
            "end_time": event.end_time.isoformat() if event.end_time else None,
            "location": event.location,
            "location_profile": location_profile,
            "preferences": event.preferences or [],
            "constraints": event.constraints or [],
        }

    @staticmethod
    def _user_dict(user) -> dict:
        if user is None:
            return {"name": "用户", "interests": [], "bio": None, "city": None}
        return {
            "name": user.name,
            "interests": user.interests or [],
            "bio": user.bio,
            "city": user.city,
        }


a2a_matcher = A2AMatcher()
