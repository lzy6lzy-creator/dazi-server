from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ws import manager as ws_manager
from app.core.database import async_session
from app.models.user import AgentMemory, EventMemory, MemoryEvidence


LONG_TERM_TYPES = {"preference", "constraint", "behavior", "style", "feedback"}


@dataclass(frozen=True)
class EventMemoryCandidate:
    user_id: UUID
    event_id: UUID
    key: str
    type: str
    category: str
    content: str
    value: dict | None = None
    source: str = "draft"
    confidence: float = 0.8


@dataclass(frozen=True)
class MemoryAction:
    action: str
    key: str
    type: str
    category: str
    content: str
    value: dict | None = None
    target_memory_id: UUID | None = None
    confidence_delta: float = 0.0
    reason: str = ""
    evidence_text: str = ""


def build_event_memory_candidates(
    *,
    user_id: UUID,
    event_id: UUID,
    draft: dict,
) -> list[EventMemoryCandidate]:
    candidates: list[EventMemoryCandidate] = []

    def add(
        content: str,
        mem_type: str = "preference",
        source: str = "draft",
        *,
        key: str | None = None,
        category: str | None = None,
        value: dict | None = None,
    ) -> None:
        cleaned = _clean_content(content)
        if not cleaned:
            return
        resolved_category = category or _category_for_text(cleaned)
        candidates.append(
            EventMemoryCandidate(
                user_id=user_id,
                event_id=event_id,
                key=key or _key_for_text(cleaned, resolved_category),
                type=mem_type,
                category=resolved_category,
                content=cleaned,
                value=value if value is not None else _value_for_text(cleaned, resolved_category),
                source=source,
                confidence=0.85 if mem_type == "constraint" else 0.75,
            )
        )

    if draft.get("activity_type"):
        activity_type = _clean_content(str(draft["activity_type"]))
        if activity_type:
            add(
                f"本次活动：{activity_type}",
                "preference",
                key=f"event.activity_type.{_stable_key_part(activity_type)}",
                category="activity",
                value={"activity_type": activity_type},
            )
    if draft.get("location"):
        location = _clean_content(str(draft["location"]))
        if location:
            add(
                location,
                "preference",
                key=f"event.location.{_stable_key_part(location)}",
                category="location",
                value={"location": location},
            )

    preferences = draft.get("preferences") if isinstance(draft.get("preferences"), list) else []
    constraints = draft.get("constraints") if isinstance(draft.get("constraints"), list) else []
    for item in preferences:
        add(str(item), "preference", "clarification")
    for item in constraints:
        add(str(item), "constraint", "clarification")

    if draft.get("age_filter_min") or draft.get("age_filter_max"):
        age_min = draft.get("age_filter_min")
        age_max = draft.get("age_filter_max")
        mode = draft.get("age_filter_mode") or "preference"
        add(f"年龄偏好：{age_min or ''}-{age_max or ''} 岁", "constraint" if mode == "hard_filter" else "preference")

    return _dedupe_event_candidates(candidates)


def derive_long_term_memory_actions(
    *,
    text: str,
    event_memories: list[EventMemoryCandidate],
    existing_memories: list[AgentMemory],
) -> list[MemoryAction]:
    actions: list[MemoryAction] = []
    explicit_actions = _explicit_long_term_actions(text, existing_memories)
    actions.extend(explicit_actions)

    explicit_keys = {action.key for action in explicit_actions if action.action != "ignore"}
    for candidate in event_memories:
        if candidate.key in explicit_keys:
            continue
        existing = _find_existing(candidate.key, existing_memories)
        if existing and (existing.occurrence_count or 1) >= 1:
            actions.append(
                MemoryAction(
                    action="reinforce",
                    target_memory_id=existing.id,
                    key=candidate.key,
                    type=existing.type or candidate.type,
                    category=existing.category or candidate.category,
                    content=existing.content or _long_term_content(candidate),
                    value=candidate.value,
                    confidence_delta=0.08,
                    reason="同类事件偏好重复出现，增强长期记忆",
                    evidence_text=candidate.content,
                )
            )
        else:
            actions.append(
                MemoryAction(
                    action="ignore",
                    key=candidate.key,
                    type=candidate.type,
                    category=candidate.category,
                    content=candidate.content,
                    value=candidate.value,
                    reason="本次活动条件，暂不升级为长期记忆",
                    evidence_text=candidate.content,
                )
            )

    if not actions and _looks_temporary(text):
        actions.append(
            MemoryAction(
                action="ignore",
                key="event.temporary",
                type="preference",
                category="other",
                content=_clean_content(text) or "本次活动条件",
                reason="临时活动表达",
                evidence_text=text.strip(),
            )
        )

    return actions


async def apply_long_term_memory_actions(
    *,
    db: AsyncSession,
    user_id: UUID,
    actions: list[MemoryAction],
    event_id: UUID | None = None,
    event_memory_ids: list[UUID] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    for action in actions:
        if action.action == "ignore":
            continue
        if action.type not in LONG_TERM_TYPES:
            continue
        if not action.content.strip():
            continue

        memory: AgentMemory | None = None
        if action.target_memory_id:
            result = await db.execute(
                select(AgentMemory).where(
                    AgentMemory.id == action.target_memory_id,
                    AgentMemory.user_id == user_id,
                )
            )
            memory = result.scalar_one_or_none()
        if not memory:
            result = await db.execute(
                select(AgentMemory).where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.key == action.key,
                    AgentMemory.is_active == True,
                )
            )
            memory = result.scalar_one_or_none()

        if action.action == "create" or memory is None:
            memory = AgentMemory(
                user_id=user_id,
                type=action.type,
                content=action.content,
                confidence=min(0.9, max(0.35, 0.55 + action.confidence_delta)),
                source="memory_updater",
                source_event_id=event_id,
                key=action.key,
                category=action.category,
                value=action.value,
                occurrence_count=1,
                last_seen_at=now,
                status="active",
            )
            db.add(memory)
            await db.flush()
        elif action.action == "reinforce":
            memory.confidence = min(1.0, (memory.confidence or 0.5) + action.confidence_delta)
            memory.occurrence_count = (memory.occurrence_count or 1) + 1
            memory.last_seen_at = now
            memory.updated_at = now
        elif action.action == "revise":
            memory.content = action.content
            memory.value = action.value
            memory.confidence = min(0.95, max(memory.confidence or 0.5, 0.65 + action.confidence_delta))
            memory.occurrence_count = (memory.occurrence_count or 1) + 1
            memory.last_seen_at = now
            memory.updated_at = now
        elif action.action == "conflict":
            memory.status = "conflicted"
            memory.is_active = False
            memory.updated_at = now
            replacement = AgentMemory(
                user_id=user_id,
                type=action.type,
                content=action.content,
                confidence=max(0.45, 0.55 + action.confidence_delta),
                source="memory_updater",
                source_event_id=event_id,
                key=action.key,
                category=action.category,
                value=action.value,
                occurrence_count=1,
                last_seen_at=now,
                status="active",
            )
            db.add(replacement)
            await db.flush()
            memory.superseded_by_id = replacement.id
            memory = replacement

        db.add(
            MemoryEvidence(
                user_id=user_id,
                memory_id=memory.id,
                event_id=event_id,
                source="event_memory",
                source_text=action.evidence_text[:500] if action.evidence_text else action.content[:500],
                event_memory_ids=[str(item) for item in (event_memory_ids or [])],
                confidence_delta=action.confidence_delta,
            )
        )
        await ws_manager.send_to_user(str(user_id), memory_updated_payload(memory, action=action.action))


async def extract_and_update_memories_after_publish(
    *,
    user_id: UUID,
    event_id: UUID,
    user_message: str,
    draft: dict,
) -> None:
    async with async_session() as db:
        event_memories = build_event_memory_candidates(user_id=user_id, event_id=event_id, draft=draft)
        event_rows: list[EventMemory] = []
        for candidate in event_memories:
            row = EventMemory(
                user_id=candidate.user_id,
                event_id=candidate.event_id,
                key=candidate.key,
                type=candidate.type,
                content=candidate.content,
                value=candidate.value,
                category=candidate.category,
                source=candidate.source,
                confidence=candidate.confidence,
            )
            db.add(row)
            event_rows.append(row)
        await db.flush()

        result = await db.execute(
            select(AgentMemory).where(
                AgentMemory.user_id == user_id,
                AgentMemory.is_active == True,
            )
        )
        existing = list(result.scalars().all())
        actions = derive_long_term_memory_actions(
            text=user_message,
            event_memories=event_memories,
            existing_memories=existing,
        )
        await apply_long_term_memory_actions(
            db=db,
            user_id=user_id,
            actions=actions,
            event_id=event_id,
            event_memory_ids=[row.id for row in event_rows],
        )
        await db.commit()


def format_memory_context(memories: list[AgentMemory]) -> str:
    if not memories:
        return "暂无记忆记录"
    lines: list[str] = []
    for memory in memories:
        type_label = {
            "preference": "偏好",
            "constraint": "限制",
            "behavior": "习惯",
            "style": "风格",
            "feedback": "反馈",
        }.get(memory.type, memory.type)
        category = memory.category or "other"
        confidence = memory.confidence if memory.confidence is not None else 0.5
        lines.append(f"- [{type_label}][{category}][confidence={confidence:.2f}] {memory.content}")
    return "\n".join(lines)


def memory_updated_payload(memory: AgentMemory, *, action: str) -> dict:
    return {
        "type": "memory_updated",
        "action": action,
        "memory": {
            "id": str(memory.id),
            "type": memory.type,
            "content": memory.content,
            "confidence": memory.confidence,
            "source": memory.source,
            "key": memory.key,
            "category": memory.category,
            "scope": memory.scope,
            "value": memory.value,
            "occurrence_count": memory.occurrence_count or 1,
            "last_seen_at": memory.last_seen_at.isoformat() if memory.last_seen_at else None,
            "status": memory.status,
            "is_active": memory.is_active,
            "created_at": memory.created_at.isoformat() if memory.created_at else None,
            "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        },
    }


def _explicit_long_term_actions(text: str, existing_memories: list[AgentMemory]) -> list[MemoryAction]:
    cleaned = _clean_content(text)
    if not cleaned:
        return []

    actions: list[MemoryAction] = []
    lowered = cleaned.lower()
    if any(token in cleaned for token in ("不能吃辣", "不吃辣", "吃不了辣")):
        actions.append(_upsert_action("不能吃辣", "constraint", "food", existing_memories, 0.25, cleaned))
    if any(token in cleaned for token in ("不喝酒", "不能喝酒")):
        actions.append(_upsert_action("不喝酒", "constraint", "alcohol", existing_memories, 0.25, cleaned))
    if any(token in cleaned for token in ("喜欢直接总结", "直接总结", "少问表单", "别问太多", "不喜欢太多表单")):
        actions.append(_upsert_action("喜欢直接总结后确认", "style", "style", existing_memories, 0.15, cleaned))
    if any(token in cleaned for token in ("一般周末", "通常周末", "周末下午")) and any(token in cleaned for token in ("一般", "通常", "一直", "以后")):
        actions.append(_upsert_action("周末下午更方便", "behavior", "time", existing_memories, 0.15, cleaned))

    if not actions and _looks_temporary(cleaned):
        actions.append(
            MemoryAction(
                action="ignore",
                key="event.temporary",
                type="preference",
                category="other",
                content=cleaned,
                reason="临时活动表达",
                evidence_text=cleaned,
            )
        )
    if not actions and any(token in lowered for token in ("记住", "以后", "一般", "通常", "一直", "不喜欢")):
        category = _category_for_text(cleaned)
        mem_type = "constraint" if any(token in cleaned for token in ("不能", "不接受", "不要")) else "preference"
        actions.append(_upsert_action(cleaned, mem_type, category, existing_memories, 0.12, cleaned))

    return actions


def _upsert_action(
    content: str,
    mem_type: str,
    category: str,
    existing_memories: list[AgentMemory],
    confidence_delta: float,
    evidence_text: str,
) -> MemoryAction:
    key = _key_for_text(content, category)
    existing = _find_existing(key, existing_memories)
    return MemoryAction(
        action="reinforce" if existing else "create",
        target_memory_id=existing.id if existing else None,
        key=key,
        type=existing.type if existing else mem_type,
        category=existing.category if existing and existing.category else category,
        content=existing.content if existing else content,
        value=_value_for_text(content, category),
        confidence_delta=confidence_delta,
        reason="用户明确表达长期偏好或限制",
        evidence_text=evidence_text,
    )


def _find_existing(key: str, existing_memories: list[AgentMemory]) -> AgentMemory | None:
    for memory in existing_memories:
        if memory.key == key:
            return memory
    return None


def _long_term_content(candidate: EventMemoryCandidate) -> str:
    if candidate.category == "activity":
        activity_type = str((candidate.value or {}).get("activity_type") or "").strip()
        if activity_type:
            return f"经常发起{activity_type}活动"
    if candidate.category == "budget" and "AA" in candidate.content.upper():
        return "偏好场地费 AA"
    return candidate.content


def _category_for_text(text: str) -> str:
    if any(token in text for token in ("辣", "火锅", "吃", "餐", "饭")):
        return "food"
    if any(token in text for token in ("场地费", "AA", "预算", "人均", "钱", "费用")):
        return "budget"
    if any(token in text for token in ("网球", "羽毛球", "篮球", "新手", "水平")):
        return "sport"
    if any(token in text for token in ("周末", "今晚", "今天", "明天", "时间", "下午", "晚上")):
        return "time"
    if any(token in text for token in ("上海", "北京", "静安", "徐汇", "浦东", "地点", "区域")):
        return "location"
    if any(token in text for token in ("总结", "表单", "直接", "问太多")):
        return "style"
    return "other"


def _key_for_text(text: str, category: str) -> str:
    if any(token in text for token in ("不能吃辣", "不吃辣", "吃不了辣")):
        return "food.spicy_tolerance"
    if any(token in text for token in ("不喝酒", "不能喝酒")):
        return "alcohol.drinking"
    if "场地费" in text and "AA" in text.upper():
        return "budget.cost_share"
    if "新手" in text:
        return "sport.skill_level"
    if "总结" in text or "表单" in text:
        return "style.confirmation"
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"{category}.{digest}"


def _stable_key_part(text: str) -> str:
    cleaned = _clean_content(text) or "unknown"
    collapsed = "_".join(cleaned.split())
    return collapsed[:60]


def _value_for_text(text: str, category: str) -> dict | None:
    if _key_for_text(text, category) == "food.spicy_tolerance":
        return {"spicy_tolerance": "none"}
    if _key_for_text(text, category) == "budget.cost_share":
        return {"mode": "aa"}
    if _key_for_text(text, category) == "style.confirmation":
        return {"reply_style": "summarize_then_confirm"}
    return None


def _looks_temporary(text: str) -> bool:
    return any(token in text for token in ("今晚", "今天", "明天", "这次", "本次", "临时", "刚好"))


def _clean_content(content: str) -> str:
    return str(content or "").replace("\n", " ").strip()[:120]


def _dedupe_event_candidates(candidates: list[EventMemoryCandidate]) -> list[EventMemoryCandidate]:
    seen: set[tuple[str, str]] = set()
    result: list[EventMemoryCandidate] = []
    for candidate in candidates:
        key = (candidate.key, candidate.content)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result
