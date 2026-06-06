from __future__ import annotations

import logging
import json
from uuid import UUID

from app.services.agent_server import agent_server
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
    issues = (
        _string_list(payload.get("conflicts"))
        + _string_list(payload.get("uncertainties"))
        + _string_list(payload.get("potential_issues"))
    )
    score_breakdown = _score_breakdown(payload.get("score_breakdown"))
    requested_match = bool(payload.get("should_match"))
    has_blocking_conflict = bool(payload.get("has_blocking_conflict"))
    should_match = (
        requested_match
        and not has_blocking_conflict
        and compatibility >= A2A_MATCH_THRESHOLD
        and not _string_list(payload.get("uncertainties"))
    )
    chatroom_carryover = str(payload.get("chatroom_carryover") or "").strip()
    summary = (
        chatroom_carryover
        if should_match and chatroom_carryover
        else str(payload.get("summary") or "A2A 未给出摘要")
    )

    return A2AEvaluation(
        source_event_id=source_event_id,
        candidate_event_id=candidate_event_id,
        compatibility=compatibility,
        should_match=should_match,
        summary=summary,
        reasons=reasons,
        issues=issues,
        score_breakdown=score_breakdown,
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


def _score_breakdown(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    rows: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if not dimension:
            continue
        rows.append({
            "dimension": dimension,
            "score": _safe_float(item.get("score")),
            "reason": str(item.get("reason") or "").strip(),
            "blocking": bool(item.get("blocking")),
        })
    return rows


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
            from app.services.prompt_builder import PromptBuilder

            prompt = PromptBuilder.build_a2a_dialogue_prompt()
            context = await self._build_a2a_context(source, candidate, db)
            dialogue: list[dict[str, str]] = []
            turns = [
                ("A", "开场：讲清自己这边关键需求，并问一个最影响 match 的问题。"),
                ("B", "回应 A，并讲清自己这边关键需求；如有必要问一个问题。"),
                ("A", "根据公开对话补问或收束；如果事件条件已清楚，可以一句轻松闲聊。"),
                ("B", "根据公开对话补问或收束；不要继续发散。"),
            ]
            for side, task in turns:
                payload = self._build_agent_turn_payload(
                    side=side,
                    task=task,
                    public_events=context["public_events"],
                    dialogue=dialogue,
                    self_private=context["private"][side],
                )
                result = await self._call_a2a_json(prompt, payload)
                message = str(result.get("message") or "").strip()
                if message:
                    dialogue.append({"speaker": side, "content": message})

            judge_payload = self._build_judge_payload(
                public_events=context["public_events"],
                dialogue=dialogue,
            )
            judge_result = await self._call_a2a_json(prompt, judge_payload)
            if isinstance(judge_result, dict):
                judge_result["dialogue"] = dialogue
            return parse_a2a_response(source.id, candidate.id, judge_result)
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

    async def _build_a2a_context(self, source, candidate, db) -> dict:
        user_a = await self._get_user(source.user_id, db)
        user_b = await self._get_user(candidate.user_id, db)
        agent_a = await self._get_agent(source.user_id, db)
        agent_b = await self._get_agent(candidate.user_id, db)
        memories_a = await self._get_memories(source.user_id, db)
        memories_b = await self._get_memories(candidate.user_id, db)

        return {
            "public_events": {
                "A": self._event_dict(source),
                "B": self._event_dict(candidate),
            },
            "private": {
                "A": self._private_dict(
                    agent_name=agent_a.name if agent_a else "AI",
                    user_info=self._user_dict(user_a),
                    memories=memories_a,
                ),
                "B": self._private_dict(
                    agent_name=agent_b.name if agent_b else "AI",
                    user_info=self._user_dict(user_b),
                    memories=memories_b,
                ),
            },
        }

    @staticmethod
    async def _call_a2a_json(prompt: str, payload: dict) -> dict:
        result = await agent_server.chat_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "请按 prompt 的 JSON 结构处理以下输入：\n"
                    + json.dumps(payload, ensure_ascii=False, indent=2),
                },
            ],
            purpose="conversation",
            temperature=0.3,
            max_tokens=2048,
        )
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _build_agent_turn_payload(
        *,
        side: str,
        task: str,
        public_events: dict,
        dialogue: list[dict[str, str]],
        self_private: dict,
    ) -> dict:
        return {
            "mode": "agent_turn",
            "self_agent": side,
            "task": task,
            "public_context": {
                "events": public_events,
                "rule": "两边 agent 都能看两个公开事件；每个 agent 只能看自己的 private。",
                "dialogue_so_far": dialogue,
            },
            "self_private": self_private,
        }

    @staticmethod
    def _build_judge_payload(
        *,
        public_events: dict,
        dialogue: list[dict[str, str]],
    ) -> dict:
        return {
            "mode": "judge",
            "public_context": {
                "events": public_events,
                "rule": "judge 只能看公开事件和双方 agent 已公开的对话，不直接读取任何私有 memory。",
            },
            "public_dialogue": dialogue,
        }

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

    @staticmethod
    def _private_dict(
        *,
        agent_name: str,
        user_info: dict,
        memories: list[tuple[str, str]],
    ) -> dict:
        return {
            "agent_name": agent_name,
            "profile": user_info,
            "memory": [
                {"type": mem_type, "content": content}
                for mem_type, content in memories
            ],
        }


a2a_matcher = A2AMatcher()
