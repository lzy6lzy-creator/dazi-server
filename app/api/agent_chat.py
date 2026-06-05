"""
Agent Chat API - 与 AI Agent 对话

功能：
- 对话历史持久化（Redis 缓存 + DB 存储）
- 主对话编排 prompt 返回 chat / clarify / draft / cancel
- 用户确认草稿后确定性创建 Event
- 发布成功后后台提取长期 Memory
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.embedding_service import embedding_service

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.core.redis import ChatHistoryCache
from app.models.user import User, Agent, AgentMemory, AgentChatMessage
from app.models.event import Event
from app.services.llm_service import llm_service
from app.services.matching_tasks import schedule_event_matching
from app.services.prompt_builder import PromptBuilder
from app.services.memory_service import extract_and_update_memories_after_publish
from app.services.clarification_service import (
    merge_clarification_answers,
    normalize_conversation_payload,
)
from app.api.schemas import AgentChatRequest, AgentChatResponse, ClarificationAnswerRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent-chat"])
BEIJING_TZ = timezone(timedelta(hours=8))
SESSION_RESET_ROLE = "session"
SESSION_RESET_PREFIX = "[SESSION_RESET_AFTER_EVENT]"


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(
    req: AgentChatRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # 1. 加载用户、Agent、Memory
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    agent_result = await db.execute(select(Agent).where(Agent.user_id == user_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    current_location = _clean_current_location(req.current_location) or _clean_current_location(user.city)

    memories_result = await db.execute(
        select(AgentMemory)
        .where(AgentMemory.user_id == user_id, AgentMemory.is_active == True)
    )
    memories = memories_result.scalars().all()

    # 2. 加载对话历史（先查 Redis，没有则从 DB session 起点之后恢复）
    uid_str = str(user_id)
    history = await _load_agent_chat_history(user_id=user_id, uid_str=uid_str, db=db)

    existing_draft = await ChatHistoryCache.get_event_draft(uid_str)
    if existing_draft:
        existing_draft = _draft_with_default_location(existing_draft, current_location)
    editing_event_id = await ChatHistoryCache.get_editing_event(uid_str)
    if _can_publish_existing_draft_without_llm(existing_draft, req.message):
        direct_response = await _publish_existing_draft_without_llm(
            user=user,
            uid_str=uid_str,
            message=req.message,
            editing_event_id=editing_event_id,
            current_location=current_location,
            background_tasks=background_tasks,
            db=db,
        )
        if direct_response:
            return direct_response

    latest_clarification = await ChatHistoryCache.get_latest_clarification_session(uid_str)
    conversation_state = _build_conversation_state(
        existing_draft=existing_draft,
        pending_clarification=latest_clarification,
        editing_event_id=editing_event_id,
    )
    system_prompt = PromptBuilder.build_conversation_orchestrator_prompt(
        user_name=user.name,
        user_city=user.city or "",
        current_location=current_location or "",
        user_interests=user.interests or [],
        user_bio=user.bio or "",
        birth_date=user.birth_date.isoformat() if user.birth_date else None,
        memories=[(m.type, m.content) for m in memories],
        conversation_state=conversation_state,
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": req.message})

    payload = await llm_service.chat_json(messages, temperature=0.3, max_tokens=2048)
    decision = normalize_conversation_payload(payload)
    logger.info(f"Conversation decision for user {user_id}: {decision.get('action')}")

    return await _apply_conversation_decision(
        user=user,
        uid_str=uid_str,
        message=req.message,
        decision=decision,
        pending_clarification=latest_clarification,
        current_location=current_location,
        db=db,
    )


@router.get("/history")
async def get_chat_history(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    """获取 Agent 对话历史"""
    result = await db.execute(
        select(AgentChatMessage)
        .where(
            AgentChatMessage.user_id == user_id,
            AgentChatMessage.role.in_(["user", "assistant"]),
        )
        .order_by(AgentChatMessage.created_at.desc())
        .limit(limit)
    )
    messages = list(reversed(result.scalars().all()))
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


@router.delete("/history")
async def clear_chat_history(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """清空 Agent 对话历史"""
    await ChatHistoryCache.clear_history(str(user_id))
    # 不删除 DB 中的历史（保留审计），只清 Redis 缓存使新对话开始
    return {"message": "对话历史已清空"}


@router.post("/clarification/answer", response_model=AgentChatResponse)
async def answer_clarification(
    req: ClarificationAnswerRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """提交结构化澄清卡片答案，并合成活动草稿。"""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    uid_str = str(user_id)
    session = await ChatHistoryCache.get_clarification_session(
        uid_str,
        req.clarification_session_id,
    )
    if not session:
        raise HTTPException(status_code=404, detail="澄清卡片已过期，请重新描述需求")

    answers = [answer.model_dump(exclude_none=True) for answer in req.answers]
    return await _complete_clarification_session(
        user=user,
        uid_str=uid_str,
        session_id=req.clarification_session_id,
        session=session,
        answers=answers,
        free_text=req.free_text,
        background_tasks=background_tasks,
        db=db,
    )


@router.get("/clarification/pending", response_model=AgentChatResponse)
async def get_pending_clarification(
    user_id: UUID = Depends(get_current_user_id),
):
    """获取用户最近一条仍可提交的结构化澄清卡片。"""
    latest = await ChatHistoryCache.get_latest_clarification_session(str(user_id))
    if not latest:
        return AgentChatResponse(reply="")

    return AgentChatResponse(
        reply=str(latest.get("reply") or ""),
        clarification_pending=True,
        clarification_session_id=str(latest.get("session_id")),
        clarification_questions=latest.get("questions") or [],
    )


# ── 后台任务 ──

async def _complete_clarification_session(
    *,
    user: User,
    uid_str: str,
    session_id: str,
    session: dict,
    answers: list[dict],
    free_text: str | None,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
) -> AgentChatResponse:
    merged = merge_clarification_answers(
        draft=session.get("draft") or {},
        questions=session.get("questions") or [],
        answers=answers,
        user_birth_date=user.birth_date,
        free_text=free_text,
    )
    merged = _draft_with_default_location(merged, _clean_current_location(session.get("current_location")))
    await ChatHistoryCache.set_event_draft(uid_str, merged)
    await ChatHistoryCache.clear_clarification_session(uid_str, session_id)

    user_answer_text = _clarification_answers_to_text(session.get("questions") or [], answers, free_text)
    reply = _draft_confirmation_reply(merged)

    await ChatHistoryCache.append_message(uid_str, "user", user_answer_text)
    await ChatHistoryCache.append_message(uid_str, "assistant", reply)
    db.add(AgentChatMessage(user_id=user.id, role="user", content=user_answer_text))
    db.add(AgentChatMessage(user_id=user.id, role="assistant", content=reply))
    await db.flush()

    return AgentChatResponse(
        reply=reply,
        event_draft_pending=True,
    )


async def _load_agent_chat_history(*, user_id: UUID, uid_str: str, db: AsyncSession) -> list[dict]:
    history = await ChatHistoryCache.get_history(uid_str)
    if history:
        return history

    session_start = await _get_agent_chat_session_start(user_id=user_id, uid_str=uid_str, db=db)
    conditions = [
        AgentChatMessage.user_id == user_id,
        AgentChatMessage.role.in_(["user", "assistant"]),
    ]
    if session_start:
        conditions.append(AgentChatMessage.created_at > session_start)

    db_msgs = await db.execute(
        select(AgentChatMessage)
        .where(*conditions)
        .order_by(AgentChatMessage.created_at.desc())
        .limit(40)
    )
    db_messages = list(reversed(db_msgs.scalars().all()))
    if not db_messages:
        return []

    history = [{"role": m.role, "content": m.content} for m in db_messages]
    await ChatHistoryCache.set_history(uid_str, history)
    return history


async def _get_agent_chat_session_start(*, user_id: UUID, uid_str: str, db: AsyncSession) -> datetime | None:
    session_start = await ChatHistoryCache.get_agent_chat_session_start(uid_str)
    if session_start:
        return session_start

    marker = await db.execute(
        select(AgentChatMessage.created_at)
        .where(
            AgentChatMessage.user_id == user_id,
            AgentChatMessage.role == SESSION_RESET_ROLE,
            AgentChatMessage.content.like(f"{SESSION_RESET_PREFIX}%"),
        )
        .order_by(AgentChatMessage.created_at.desc())
        .limit(1)
    )
    marker_time = marker.scalar_one_or_none()
    if marker_time:
        await ChatHistoryCache.start_new_agent_chat_session(uid_str, started_at=marker_time)
    return marker_time


def _build_conversation_state(
    *,
    existing_draft: dict | None,
    pending_clarification: dict | None,
    editing_event_id: str | None,
) -> str:
    import json as json_lib

    parts = []
    if editing_event_id:
        parts.append(f"正在编辑活动，event_id={editing_event_id}")
    if existing_draft:
        parts.append("当前已有待确认活动草稿：")
        parts.append(json_lib.dumps(existing_draft, ensure_ascii=False))
    if pending_clarification:
        state = {
            "reply": pending_clarification.get("reply"),
            "draft": pending_clarification.get("draft") or {},
            "questions": pending_clarification.get("questions") or [],
        }
        parts.append("当前有待回答的澄清卡片：")
        parts.append(json_lib.dumps(state, ensure_ascii=False))
    return "\n".join(parts) if parts else "无待处理状态"


async def _persist_agent_exchange(
    *,
    user_id: UUID,
    uid_str: str,
    user_message: str,
    assistant_reply: str,
    db: AsyncSession,
) -> None:
    await ChatHistoryCache.append_message(uid_str, "user", user_message)
    await ChatHistoryCache.append_message(uid_str, "assistant", assistant_reply)
    db.add(AgentChatMessage(user_id=user_id, role="user", content=user_message))
    db.add(AgentChatMessage(user_id=user_id, role="assistant", content=assistant_reply))
    await db.flush()


async def _clear_pending_clarification_if_any(uid_str: str, pending_clarification: dict | None) -> None:
    session_id = str((pending_clarification or {}).get("session_id") or "")
    if session_id:
        await ChatHistoryCache.clear_clarification_session(uid_str, session_id)


async def _apply_conversation_decision(
    *,
    user: User,
    uid_str: str,
    message: str,
    decision: dict,
    pending_clarification: dict | None,
    current_location: str | None,
    db: AsyncSession,
) -> AgentChatResponse:
    action = decision.get("action") or "chat"
    reply = decision.get("reply") or "我在，你再跟我说说。"
    draft = _draft_with_default_location(decision.get("draft") or {}, current_location)
    questions = decision.get("questions") or []

    if action == "cancel":
        await _clear_pending_clarification_if_any(uid_str, pending_clarification)
        await ChatHistoryCache.clear_event_draft(uid_str)
        await ChatHistoryCache.clear_editing_event(uid_str)
        await _persist_agent_exchange(
            user_id=user.id,
            uid_str=uid_str,
            user_message=message,
            assistant_reply=reply,
            db=db,
        )
        return AgentChatResponse(reply=reply)

    if action == "clarify" and questions:
        await _clear_pending_clarification_if_any(uid_str, pending_clarification)
        session_id = str(uuid4())
        await ChatHistoryCache.set_clarification_session(
            uid_str,
            session_id,
            {
                "reply": reply,
                "original_message": message,
                "draft": draft,
                "current_location": current_location,
                "questions": questions,
            },
        )
        await _persist_agent_exchange(
            user_id=user.id,
            uid_str=uid_str,
            user_message=message,
            assistant_reply=reply,
            db=db,
        )
        return AgentChatResponse(
            reply=reply,
            clarification_pending=True,
            clarification_session_id=session_id,
            clarification_questions=questions,
        )

    if action == "draft" and draft:
        await _clear_pending_clarification_if_any(uid_str, pending_clarification)
        await ChatHistoryCache.set_event_draft(uid_str, draft)
        if not decision.get("reply"):
            reply = _draft_confirmation_reply(draft)
        await _persist_agent_exchange(
            user_id=user.id,
            uid_str=uid_str,
            user_message=message,
            assistant_reply=reply,
            db=db,
        )
        return AgentChatResponse(
            reply=reply,
            event_draft_pending=True,
        )

    await _persist_agent_exchange(
        user_id=user.id,
        uid_str=uid_str,
        user_message=message,
        assistant_reply=reply,
        db=db,
    )
    return AgentChatResponse(reply=reply)


def _looks_like_confirmation(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    direct_confirmations = {"确认", "可以", "好的", "好", "没问题", "ok", "okay", "yes", "go"}
    if text in direct_confirmations:
        return True
    confirmation_phrases = ("确认发布", "帮我发布", "发吧", "就这样", "没问题，发布")
    return any(phrase in text for phrase in confirmation_phrases)


def _can_publish_existing_draft_without_llm(draft: dict | None, message: str) -> bool:
    return bool(draft) and _looks_like_confirmation(message)


def _clean_current_location(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    invalid_values = {
        "位置未知",
        "未知位置",
        "位置获取中",
        "位置获取中...",
        "位置获取失败",
        "位置权限未授予",
        "未设置",
        "未填写",
    }
    return None if text in invalid_values else text


def _draft_with_default_location(draft: dict | None, current_location: str | None) -> dict:
    if not isinstance(draft, dict):
        return {}
    cleaned = dict(draft)
    legacy_city = _clean_current_location(cleaned.pop("city", None))
    location = _clean_current_location(cleaned.get("location")) or legacy_city
    default_location = _clean_current_location(current_location)
    if not location and default_location:
        location = default_location
    if location:
        cleaned["location"] = location
        _remove_place_from_draft_lists(cleaned, [location, legacy_city])
    else:
        cleaned.pop("location", None)
    return cleaned


def _remove_place_from_draft_lists(draft: dict, labels: list[str | None]) -> None:
    label_set = {label.strip() for label in labels if isinstance(label, str) and label.strip()}
    if not label_set:
        return
    for field in ("preferences", "constraints"):
        values = draft.get(field)
        if isinstance(values, list):
            draft[field] = [item for item in values if item not in label_set]


def _build_memory_source_after_publish(*, user_message: str, draft: dict) -> str:
    title = draft.get("title") or draft.get("activity_type") or "未命名活动"
    activity_type = draft.get("activity_type") or "未填写"
    place = draft.get("location") or "未填写"
    preferences = draft.get("preferences") if isinstance(draft.get("preferences"), list) else []
    constraints = draft.get("constraints") if isinstance(draft.get("constraints"), list) else []
    lines = [
        "用户发布了一次活动，请只提取长期稳定偏好，不要把一次性安排当作长期记忆。",
        f"用户最后确认消息：{(user_message or '').strip()}",
        f"活动标题：{title}",
        f"活动类型：{activity_type}",
        f"地点：{place}",
        f"偏好：{'、'.join(preferences) if preferences else '无'}",
        f"限制：{'、'.join(constraints) if constraints else '无'}",
    ]
    return "\n".join(lines)


async def _publish_existing_draft_without_llm(
    *,
    user: User,
    uid_str: str,
    message: str,
    editing_event_id: str | None,
    current_location: str | None,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
) -> AgentChatResponse | None:
    reply = "好，我帮你发布找搭子。"
    draft = await ChatHistoryCache.get_event_draft(uid_str) or {}
    draft = _draft_with_default_location(draft, current_location)
    await ChatHistoryCache.append_message(uid_str, "user", message)
    await ChatHistoryCache.append_message(uid_str, "assistant", reply)
    db.add(AgentChatMessage(user_id=user.id, role="user", content=message))
    db.add(AgentChatMessage(user_id=user.id, role="assistant", content=reply))
    await db.flush()

    created_new_event = False
    if editing_event_id:
        event_id = await _update_event_from_draft(
            user_id=user.id,
            uid_str=uid_str,
            event_id_str=editing_event_id,
            current_location=current_location,
            db=db,
        )
    else:
        event_id = await _create_event_from_draft(
            user_id=user.id,
            uid_str=uid_str,
            current_location=current_location,
            db=db,
        )
        created_new_event = event_id is not None

    if event_id is None:
        return AgentChatResponse(reply="发布时出了点问题，请稍后再试。")

    if created_new_event:
        schedule_event_matching(background_tasks, event_id)
        if draft:
            background_tasks.add_task(
                _extract_memories_background,
                user_id=user.id,
                event_id=event_id,
                user_message=message,
                draft=draft,
            )

    await _start_new_agent_chat_session_after_event_ready(
        user_id=user.id,
        uid_str=uid_str,
        event_id=event_id,
        db=db,
    )

    return AgentChatResponse(
        reply=reply,
        event_ready=True,
        event_id=event_id,
    )


async def _start_new_agent_chat_session_after_event_ready(
    *,
    user_id: UUID,
    uid_str: str,
    event_id: UUID,
    db: AsyncSession,
) -> None:
    marker = AgentChatMessage(
        user_id=user_id,
        role=SESSION_RESET_ROLE,
        content=f"{SESSION_RESET_PREFIX}:{event_id}",
    )
    db.add(marker)
    await db.flush()
    await ChatHistoryCache.start_new_agent_chat_session(uid_str, started_at=marker.created_at)


def _clarification_answers_to_text(
    questions: list[dict],
    answers: list[dict],
    free_text: str | None,
) -> str:
    question_by_id = {
        str(question.get("id")): question
        for question in questions
        if isinstance(question, dict) and question.get("id")
    }
    lines = ["我已选择澄清卡片："]
    for answer in answers:
        question = question_by_id.get(str(answer.get("question_id") or ""))
        if not question:
            continue
        labels = _answer_labels(question, answer)
        if labels:
            lines.append(f"- {question.get('title')}: {', '.join(labels)}")
    if free_text:
        lines.append(f"- 补充说明: {free_text.strip()}")
    return "\n".join(lines)


def _answer_labels(question: dict, answer: dict) -> list[str]:
    option_ids = answer.get("option_ids")
    if not isinstance(option_ids, list):
        option_ids = []
    options = {
        str(option.get("id")): option
        for option in question.get("options", [])
        if isinstance(option, dict)
    }
    labels = [
        str(options[option_id].get("label"))
        for option_id in option_ids
        if option_id in options and options[option_id].get("label")
    ]
    custom_value = answer.get("custom_value")
    if isinstance(custom_value, dict):
        min_age = custom_value.get("min_age")
        max_age = custom_value.get("max_age")
        if min_age is not None and max_age is not None:
            labels.append(f"{min_age}-{max_age} 岁")
    elif isinstance(custom_value, str) and custom_value.strip():
        labels.append(custom_value.strip())
    return labels


def _draft_confirmation_reply(draft: dict) -> str:
    title = draft.get("title") or draft.get("activity_type") or "这次活动"
    activity_type = draft.get("activity_type")
    location = draft.get("location")
    preferences = draft.get("preferences") or []
    constraints = draft.get("constraints") or []

    parts = [f"我帮你整理好了：{title}"]
    if activity_type and activity_type != title:
        parts.append(f"类型是 {activity_type}")
    if location:
        parts.append(f"地点偏向 {location}")
    if preferences:
        parts.append(f"偏好：{'、'.join(preferences[:4])}")
    if constraints:
        parts.append(f"限制：{'、'.join(constraints[:4])}")
    return "；".join(parts) + "。确认的话，我就帮你发布找搭子。"


def _editing_event_intro_reply(
    *,
    title: str,
    activity_type: str | None,
    start_time_text: str,
    place_text: str,
    preferences: list[str],
    constraints: list[str],
) -> str:
    parts = [f"当前活动是：{title}"]
    if activity_type:
        parts.append(f"类型是 {activity_type}")
    if start_time_text:
        parts.append(f"时间是 {start_time_text}")
    if place_text:
        parts.append(f"地点是 {place_text}")
    if preferences:
        parts.append(f"偏好：{'、'.join(preferences[:4])}")
    if constraints:
        parts.append(f"限制：{'、'.join(constraints[:4])}")
    return "；".join(parts) + "。直接告诉我你想改哪里，我会重新整理一版给你确认。"


async def _extract_memories_background(
    *,
    user_id: UUID,
    event_id: UUID,
    user_message: str,
    draft: dict,
):
    """后台提取事件偏好，并自动更新长期 Memory"""
    try:
        await extract_and_update_memories_after_publish(
            user_id=user_id,
            event_id=event_id,
            user_message=user_message,
            draft=draft,
        )
        logger.info(f"Updated layered memories for user {user_id} event {event_id}")
    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")


def _event_title_from_draft(draft: dict) -> str:
    title = _clean_current_location(draft.get("title"))
    if title and title != "新活动":
        return title[:200]

    activity_type = _clean_current_location(draft.get("activity_type")) or "其他"
    preferences = draft.get("preferences") if isinstance(draft.get("preferences"), list) else []
    time_hint = next(
        (
            item
            for item in preferences
            if isinstance(item, str)
            and any(keyword in item for keyword in ("今天", "明天", "周", "晚上", "下午", "上午", "中午"))
        ),
        "",
    )
    return f"{time_hint}{activity_type}"[:200] if time_hint else activity_type[:200]


def _parse_draft_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TZ)
    return parsed


async def _create_event_from_draft(
    user_id: UUID,
    uid_str: str,
    current_location: str | None,
    db: AsyncSession,
) -> UUID | None:
    """从 Redis 中存储的 event draft 创建 Event。"""
    try:
        draft = await ChatHistoryCache.get_event_draft(uid_str)
        if not draft:
            logger.warning(f"No event draft found for user {user_id}, skipping event creation")
            return None

        draft = _draft_with_default_location(draft, current_location)
        location_value = draft.get("location")
        event = Event(
            user_id=user_id,
            title=_event_title_from_draft(draft),
            activity_type=draft.get("activity_type", "其他"),
            location=location_value,
            city=None,
            city_normalized=None,
            preferences=draft.get("preferences", []),
            constraints=draft.get("constraints", []),
            clarification_answers=draft.get("clarification_answers"),
            age_filter_min=draft.get("age_filter_min"),
            age_filter_max=draft.get("age_filter_max"),
            age_filter_mode=draft.get("age_filter_mode"),
            status="pending",
        )

        # 解析时间（如果 draft 中包含）
        for time_field in ("start_time", "end_time"):
            parsed_time = _parse_draft_datetime(draft.get(time_field))
            if parsed_time:
                setattr(event, time_field, parsed_time)

        db.add(event)
        await db.flush()

        # 生成 embedding
        text = embedding_service.build_event_text(
            event.title, event.activity_type, None,
            event.location, event.preferences, event.constraints
        )
        event.embedding = await embedding_service.encode(text)

        # 清除已使用的 draft
        await ChatHistoryCache.clear_event_draft(uid_str)

        logger.info(f"Created event {event.id} from draft for user {user_id}: {event.title}")
        return event.id

    except Exception as e:
        logger.error(f"Event creation from draft failed: {e}")
        return None


async def _update_event_from_draft(
    user_id: UUID,
    uid_str: str,
    event_id_str: str,
    db: AsyncSession,
    current_location: str | None = None,
) -> UUID | None:
    """从 Redis 中存储的 EVENT_DRAFT 更新已有 Event（编辑模式）"""
    try:
        draft = await ChatHistoryCache.get_event_draft(uid_str)
        if not draft:
            logger.warning(f"No event draft found for user {user_id}, skipping event update")
            return None
        draft = _draft_with_default_location(draft, current_location)

        from uuid import UUID as UUIDType
        event_id = UUIDType(event_id_str)
        result = await db.execute(
            select(Event).where(Event.id == event_id, Event.user_id == user_id)
        )
        event = result.scalar_one_or_none()
        if not event:
            logger.warning(f"Event {event_id_str} not found for user {user_id}")
            return None
        if event.status != "pending":
            logger.warning(f"Event {event_id_str} status is {event.status}, cannot edit")
            return None

        # 更新事件字段
        if draft.get("title"):
            event.title = _event_title_from_draft(draft)
        if draft.get("activity_type"):
            event.activity_type = draft["activity_type"]
        if "location" in draft:
            event.location = draft["location"]
            event.city = None
            event.city_normalized = None
        if "preferences" in draft:
            event.preferences = draft["preferences"]
        if "constraints" in draft:
            event.constraints = draft["constraints"]
        if "clarification_answers" in draft:
            event.clarification_answers = draft["clarification_answers"]
        if "age_filter_min" in draft:
            event.age_filter_min = draft["age_filter_min"]
        if "age_filter_max" in draft:
            event.age_filter_max = draft["age_filter_max"]
        if "age_filter_mode" in draft:
            event.age_filter_mode = draft["age_filter_mode"]

        # 解析时间
        for time_field in ("start_time", "end_time"):
            parsed_time = _parse_draft_datetime(draft.get(time_field))
            if parsed_time:
                setattr(event, time_field, parsed_time)

        # 重新生成 embedding
        text = embedding_service.build_event_text(
            event.title, event.activity_type, None,
            event.location, event.preferences, event.constraints
        )
        event.embedding = await embedding_service.encode(text)

        await db.flush()

        # 清除 draft 和编辑状态
        await ChatHistoryCache.clear_event_draft(uid_str)
        await ChatHistoryCache.clear_editing_event(uid_str)

        logger.info(f"Updated event {event.id} from draft for user {user_id}: {event.title}")
        return event.id

    except Exception as e:
        logger.error(f"Event update from draft failed: {e}")
        return None


@router.post("/edit-event/{event_id}", response_model=AgentChatResponse)
async def start_edit_event(
    event_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    发起编辑事件：将事件信息加载到对话上下文，进入编辑模式。

    Agent 会展示当前事件信息，用户可以告知需要修改的部分，
    确认后通过主对话编排草稿和确认按钮更新事件。
    """
    # 1. 检查事件存在且属于当前用户
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.user_id == user_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="活动不存在或无权修改")
    if event.status != "pending":
        raise HTTPException(status_code=400, detail=f"活动状态为 {event.status}，只有待匹配的活动可以编辑")

    # 2. 加载用户
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 3. 在 Redis 中标记编辑状态，并保存当前活动草稿作为后续修改基础
    uid_str = str(user_id)
    await ChatHistoryCache.set_editing_event(uid_str, str(event_id))
    current_draft = {
        "title": event.title,
        "activity_type": event.activity_type,
        "location": event.location or event.city,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "end_time": event.end_time.isoformat() if event.end_time else None,
        "preferences": event.preferences or [],
        "constraints": event.constraints or [],
        "clarification_answers": event.clarification_answers,
        "age_filter_min": event.age_filter_min,
        "age_filter_max": event.age_filter_max,
        "age_filter_mode": event.age_filter_mode,
    }
    await ChatHistoryCache.set_event_draft(uid_str, current_draft)

    place_text = event.location or event.city or "未设"
    reply = _editing_event_intro_reply(
        title=event.title,
        activity_type=event.activity_type,
        start_time_text=event.start_time.strftime("%Y年%m月%d日 %H:%M") if event.start_time else "未设",
        place_text=place_text,
        preferences=event.preferences or [],
        constraints=event.constraints or [],
    )
    user_context = f"我要修改活动：{event.title}"

    # 4. 持久化干净的编辑入口消息，后续 /chat 使用主编排 prompt 接管
    await ChatHistoryCache.append_message(uid_str, "user", user_context)
    await ChatHistoryCache.append_message(uid_str, "assistant", reply)

    db.add(AgentChatMessage(user_id=user_id, role="user", content=user_context))
    db.add(AgentChatMessage(user_id=user_id, role="assistant", content=reply))
    await db.flush()

    return AgentChatResponse(
        reply=reply,
        event_ready=False,
        event_id=event_id,
        event_draft_pending=False,
    )
