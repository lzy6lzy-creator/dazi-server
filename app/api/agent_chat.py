"""
Agent Chat API - 与 AI Agent 对话

功能：
- 对话历史持久化（Redis 缓存 + DB 存储）
- 对话后自动提取 Memory
- EVENT_READY 时自动提取活动信息并创建 Event
"""
from __future__ import annotations

import logging
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
from app.services.clarification_service import (
    merge_clarification_answers,
    normalize_clarification_payload,
)
from app.api.schemas import AgentChatRequest, AgentChatResponse, ClarificationAnswerRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent-chat"])


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

    memories_result = await db.execute(
        select(AgentMemory)
        .where(AgentMemory.user_id == user_id, AgentMemory.is_active == True)
    )
    memories = memories_result.scalars().all()

    # 2. 加载对话历史（先查 Redis，没有则从 DB 恢复）
    uid_str = str(user_id)
    history = await ChatHistoryCache.get_history(uid_str)

    if not history:
        # 从 DB 恢复最近对话
        db_msgs = await db.execute(
            select(AgentChatMessage)
            .where(AgentChatMessage.user_id == user_id)
            .order_by(AgentChatMessage.created_at.desc())
            .limit(40)
        )
        db_messages = list(reversed(db_msgs.scalars().all()))
        if db_messages:
            history = [{"role": m.role, "content": m.content} for m in db_messages]
            await ChatHistoryCache.set_history(uid_str, history)

    existing_draft = await ChatHistoryCache.get_event_draft(uid_str)
    editing_event_id = await ChatHistoryCache.get_editing_event(uid_str)
    if not existing_draft and not editing_event_id:
        pending_response = await _try_answer_pending_clarification_with_free_text(
            user=user,
            uid_str=uid_str,
            message=req.message,
            background_tasks=background_tasks,
            db=db,
        )
        if pending_response:
            return pending_response

        if not _looks_like_confirmation(req.message):
            clarification_response = await _try_build_clarification_response(
                user=user,
                uid_str=uid_str,
                message=req.message,
                background_tasks=background_tasks,
                db=db,
            )
            if clarification_response:
                return clarification_response

    # 3. 构建 system prompt
    system_prompt = PromptBuilder.build_agent_chat_prompt(
        agent_name=agent.name,
        agent_personality=agent.personality or "",
        user_name=user.name,
        user_interests=user.interests or [],
        user_bio=user.bio or "",
        memories=[(m.type, m.content) for m in memories],
        user_city=user.city or "",
    )

    # 4. 构建完整消息列表（system + history + 当前消息）
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": req.message})

    # 5. 调用 LLM
    reply = await llm_service.chat(messages)
    logger.info(f"LLM reply for user {user_id}: {reply[:200]}")

    # 6. 检测 [EVENT_DRAFT] 和 [EVENT_READY]
    import re
    import json as json_lib

    event_ready = "[EVENT_READY]" in reply
    clean_reply = reply.replace("[EVENT_READY]", "").strip()

    # 解析 [EVENT_DRAFT]{...}[/EVENT_DRAFT]，存入 Redis
    draft_pending = False
    draft_match = re.search(r'\[EVENT_DRAFT\](.*?)\[/EVENT_DRAFT\]', clean_reply, re.DOTALL)
    if draft_match:
        draft_json_str = draft_match.group(1).strip()
        clean_reply = re.sub(r'\[EVENT_DRAFT\].*?\[/EVENT_DRAFT\]', '', clean_reply, flags=re.DOTALL).strip()
        try:
            draft_data = json_lib.loads(draft_json_str)
            await ChatHistoryCache.set_event_draft(uid_str, draft_data)
            draft_pending = True
            logger.info(f"Stored event draft for user {user_id}: {draft_data.get('title')}")
        except json_lib.JSONDecodeError:
            logger.warning(f"Failed to parse EVENT_DRAFT JSON: {draft_json_str}")

    # 7. 持久化对话历史到 Redis 和 DB
    await ChatHistoryCache.append_message(uid_str, "user", req.message)
    await ChatHistoryCache.append_message(uid_str, "assistant", clean_reply)

    # DB 持久化
    db.add(AgentChatMessage(user_id=user_id, role="user", content=req.message))
    db.add(AgentChatMessage(user_id=user_id, role="assistant", content=clean_reply))
    await db.flush()

    # 8. 后台任务：提取 Memory
    background_tasks.add_task(
        _extract_memories_background,
        user_id=user_id,
        text=req.message,
    )

    # 9. 如果 event_ready，从已存储的 draft 创建或更新 Event（不再调 LLM）
    event_id = None
    created_new_event = False
    if event_ready:
        # 检查是否在编辑模式
        editing_event_id = await ChatHistoryCache.get_editing_event(uid_str)
        if editing_event_id:
            event_id = await _update_event_from_draft(
                user_id=user_id,
                uid_str=uid_str,
                event_id_str=editing_event_id,
                db=db,
            )
            if event_id is None:
                # 编辑失败（事件不存在/已取消等），清除残留状态，回退到新建
                await ChatHistoryCache.clear_editing_event(uid_str)
                event_id = await _create_event_from_draft(
                    user_id=user_id,
                    uid_str=uid_str,
                    user_city=user.city,
                    db=db,
                )
                created_new_event = event_id is not None
        else:
            event_id = await _create_event_from_draft(
                user_id=user_id,
                uid_str=uid_str,
                user_city=user.city,
                db=db,
            )
            created_new_event = event_id is not None

    if created_new_event and event_id is not None:
        schedule_event_matching(background_tasks, event_id)

    return AgentChatResponse(
        reply=clean_reply,
        event_ready=event_ready,
        event_id=event_id,
        event_draft_pending=draft_pending,
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
        .where(AgentChatMessage.user_id == user_id)
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

async def _try_answer_pending_clarification_with_free_text(
    *,
    user: User,
    uid_str: str,
    message: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
) -> AgentChatResponse | None:
    free_text = (message or "").strip()
    if not free_text:
        return None

    latest = await ChatHistoryCache.get_latest_clarification_session(uid_str)
    if not latest:
        return None

    session_id = str(latest.get("session_id") or "")
    if not session_id:
        return None

    return await _complete_clarification_session(
        user=user,
        uid_str=uid_str,
        session_id=session_id,
        session=latest,
        answers=[],
        free_text=free_text,
        background_tasks=background_tasks,
        db=db,
    )


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
    await ChatHistoryCache.set_event_draft(uid_str, merged)
    await ChatHistoryCache.clear_clarification_session(uid_str, session_id)

    user_answer_text = _clarification_answers_to_text(session.get("questions") or [], answers, free_text)
    reply = _draft_confirmation_reply(merged)

    await ChatHistoryCache.append_message(uid_str, "user", user_answer_text)
    await ChatHistoryCache.append_message(uid_str, "assistant", reply)
    db.add(AgentChatMessage(user_id=user.id, role="user", content=user_answer_text))
    db.add(AgentChatMessage(user_id=user.id, role="assistant", content=reply))
    await db.flush()

    if free_text:
        background_tasks.add_task(
            _extract_memories_background,
            user_id=user.id,
            text=free_text,
        )

    return AgentChatResponse(
        reply=reply,
        event_draft_pending=True,
    )

async def _try_build_clarification_response(
    *,
    user: User,
    uid_str: str,
    message: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
) -> AgentChatResponse | None:
    """让 LLM 先生成结构化澄清卡片；没有问题时回退到普通聊天。"""
    prompt = PromptBuilder.build_clarification_questions_prompt(
        user_name=user.name,
        user_city=user.city or "",
        user_interests=user.interests or [],
        birth_date=user.birth_date.isoformat() if user.birth_date else None,
    )
    payload = await llm_service.chat_json([
        {"role": "system", "content": prompt},
        {"role": "user", "content": message},
    ])
    normalized = normalize_clarification_payload(payload)
    questions = normalized.get("questions") or []
    if not questions:
        return None

    session_id = str(uuid4())
    reply = normalized.get("reply") or "我先帮你确认几个会影响匹配的小问题。"
    await ChatHistoryCache.set_clarification_session(
        uid_str,
        session_id,
        {
            "reply": reply,
            "original_message": message,
            "draft": normalized.get("draft") or {},
            "questions": questions,
        },
    )

    await ChatHistoryCache.append_message(uid_str, "user", message)
    await ChatHistoryCache.append_message(uid_str, "assistant", reply)
    db.add(AgentChatMessage(user_id=user.id, role="user", content=message))
    db.add(AgentChatMessage(user_id=user.id, role="assistant", content=reply))
    await db.flush()

    background_tasks.add_task(
        _extract_memories_background,
        user_id=user.id,
        text=message,
    )

    return AgentChatResponse(
        reply=reply,
        clarification_pending=True,
        clarification_session_id=session_id,
        clarification_questions=questions,
    )


def _looks_like_confirmation(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    direct_confirmations = {"确认", "可以", "好的", "好", "没问题", "ok", "okay", "yes", "go"}
    if text in direct_confirmations:
        return True
    confirmation_phrases = ("确认发布", "帮我发布", "发吧", "就这样", "没问题，发布")
    return any(phrase in text for phrase in confirmation_phrases)


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
    city = draft.get("city")
    location = draft.get("location")
    preferences = draft.get("preferences") or []
    constraints = draft.get("constraints") or []

    parts = [f"我帮你整理好了：{title}"]
    if activity_type and activity_type != title:
        parts.append(f"类型是 {activity_type}")
    place = " / ".join([item for item in [city, location] if item])
    if place:
        parts.append(f"地点偏向 {place}")
    if preferences:
        parts.append(f"偏好：{'、'.join(preferences[:4])}")
    if constraints:
        parts.append(f"限制：{'、'.join(constraints[:4])}")
    return "；".join(parts) + "。确认的话，我就帮你发布找搭子。"

async def _extract_memories_background(user_id: UUID, text: str):
    """后台提取用户 Memory"""
    from app.core.database import async_session

    try:
        messages = [
            {"role": "system", "content": PromptBuilder.build_memory_extraction_prompt()},
            {"role": "user", "content": text},
        ]
        result = await llm_service.chat_json(messages)

        if not result or not isinstance(result, list):
            return

        async with async_session() as db:
            for item in result:
                mem_type = item.get("type", "preference")
                content = item.get("content", "")
                if not content:
                    continue

                # 查重：如果已有相似记忆，增强 confidence
                import re as _re
                safe_content = _re.sub(r'[%_\\]', r'\\\g<0>', content[:15])
                existing = await db.execute(
                    select(AgentMemory).where(
                        AgentMemory.user_id == user_id,
                        AgentMemory.type == mem_type,
                        AgentMemory.is_active == True,
                        AgentMemory.content.ilike(f"%{safe_content}%"),
                    )
                )
                existing_mem = existing.scalar_one_or_none()

                if existing_mem:
                    existing_mem.confidence = min(1.0, existing_mem.confidence + 0.1)
                else:
                    db.add(AgentMemory(
                        user_id=user_id,
                        type=mem_type,
                        content=content,
                        confidence=0.5,
                        source="chat",
                    ))

            await db.commit()
            logger.info(f"Extracted {len(result)} memories for user {user_id}")

    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")


async def _create_event_from_draft(
    user_id: UUID,
    uid_str: str,
    user_city: str | None,
    db: AsyncSession,
) -> UUID | None:
    """从 Redis 中存储的 EVENT_DRAFT 创建 Event，无 draft 时兜底从对话提取"""
    try:
        draft = await ChatHistoryCache.get_event_draft(uid_str)
        if not draft:
            # 兜底：LLM 跳过了 EVENT_DRAFT，从对话历史提取事件信息
            logger.info(f"No draft for user {user_id}, extracting from conversation")
            history = await ChatHistoryCache.get_history(uid_str)
            if history:
                conv_text = "\n".join(
                    f"{m['role']}: {m['content']}" for m in history[-10:]
                )
                extract_messages = [
                    {"role": "system", "content": PromptBuilder.build_event_extraction_prompt()},
                    {"role": "user", "content": conv_text},
                ]
                draft = await llm_service.chat_json(extract_messages)
            if not draft:
                logger.warning(f"Failed to extract event from conversation for user {user_id}")
                return None
            logger.info(f"Extracted event from conversation for user {user_id}: {draft.get('title')}")

        city_value = draft.get("city")
        event = Event(
            user_id=user_id,
            title=draft.get("title", "新活动"),
            activity_type=draft.get("activity_type", "其他"),
            location=draft.get("location"),
            city=city_value,
            city_normalized=await embedding_service.align_city(city_value),
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
            if draft.get(time_field):
                try:
                    from datetime import datetime
                    setattr(event, time_field, datetime.fromisoformat(draft[time_field]))
                except (ValueError, TypeError):
                    pass

        db.add(event)
        await db.flush()

        # 生成 embedding
        text = embedding_service.build_event_text(
            event.title, event.activity_type, event.city,
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
) -> UUID | None:
    """从 Redis 中存储的 EVENT_DRAFT 更新已有 Event（编辑模式）"""
    try:
        draft = await ChatHistoryCache.get_event_draft(uid_str)
        if not draft:
            logger.warning(f"No event draft found for user {user_id}, skipping event update")
            return None

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
            event.title = draft["title"]
        if draft.get("activity_type"):
            event.activity_type = draft["activity_type"]
        if "location" in draft:
            event.location = draft["location"]
        if "city" in draft:
            event.city = draft["city"]
        if "city" in draft:
            event.city_normalized = await embedding_service.align_city(event.city)
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
            if draft.get(time_field):
                try:
                    from datetime import datetime
                    setattr(event, time_field, datetime.fromisoformat(draft[time_field]))
                except (ValueError, TypeError):
                    pass

        # 重新生成 embedding
        text = embedding_service.build_event_text(
            event.title, event.activity_type, event.city,
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
    确认后通过 EVENT_DRAFT + EVENT_READY 流程更新事件。
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

    # 2. 加载用户和 Agent
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    agent_result = await db.execute(select(Agent).where(Agent.user_id == user_id))
    agent = agent_result.scalar_one_or_none()
    if not user or not agent:
        raise HTTPException(status_code=404, detail="用户或 Agent 不存在")

    memories_result = await db.execute(
        select(AgentMemory)
        .where(AgentMemory.user_id == user_id, AgentMemory.is_active == True)
    )
    memories = memories_result.scalars().all()

    # 3. 在 Redis 中标记编辑状态
    uid_str = str(user_id)
    await ChatHistoryCache.set_editing_event(uid_str, str(event_id))

    # 4. 构建带编辑上下文的消息
    edit_context = f"""用户想要修改已发布的活动。请展示当前活动信息并询问要修改什么。

当前活动信息：
- 标题：{event.title}
- 类型：{event.activity_type}
- 时间：{event.start_time.strftime('%Y年%m月%d日 %H:%M') if event.start_time else '未设'}
- 地点：{event.location or '未设'}
- 偏好：{', '.join(event.preferences) if event.preferences else '无'}
- 限制：{', '.join(event.constraints) if event.constraints else '无'}

请用自然的方式告诉用户当前活动信息，然后问他想修改哪些部分。
用户修改确认后，使用和创建时一样的 [EVENT_DRAFT] + [EVENT_READY] 流程来提交修改。"""

    # 5. 构建 system prompt + 发消息给 LLM
    system_prompt = PromptBuilder.build_agent_chat_prompt(
        agent_name=agent.name,
        agent_personality=agent.personality or "",
        user_name=user.name,
        user_interests=user.interests or [],
        user_bio=user.bio or "",
        memories=[(m.type, m.content) for m in memories],
        user_city=user.city or "",
    )

    history = await ChatHistoryCache.get_history(uid_str)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": edit_context})

    reply = await llm_service.chat(messages)

    # 解析回复中的 EVENT_DRAFT 和清理标记
    import re
    import json as json_lib

    draft_pending = False
    draft_match = re.search(r'\[EVENT_DRAFT\](.*?)\[/EVENT_DRAFT\]', reply, re.DOTALL)
    if draft_match:
        draft_json_str = draft_match.group(1).strip()
        try:
            draft_data = json_lib.loads(draft_json_str)
            await ChatHistoryCache.set_event_draft(uid_str, draft_data)
            draft_pending = True
            logger.info(f"Stored edit draft for user {user_id}: {draft_data.get('title')}")
        except json_lib.JSONDecodeError:
            logger.warning(f"Failed to parse EVENT_DRAFT JSON in edit: {draft_json_str}")

    clean_reply = reply.replace("[EVENT_READY]", "").strip()
    clean_reply = re.sub(r'\[EVENT_DRAFT\].*?\[/EVENT_DRAFT\]', '', clean_reply, flags=re.DOTALL).strip()

    # 6. 持久化（存完整 edit_context 以便后续 /chat 调用时 LLM 能看到编辑指令）
    await ChatHistoryCache.append_message(uid_str, "user", edit_context)
    await ChatHistoryCache.append_message(uid_str, "assistant", clean_reply)

    db.add(AgentChatMessage(user_id=user_id, role="user", content=edit_context))
    db.add(AgentChatMessage(user_id=user_id, role="assistant", content=clean_reply))
    await db.flush()

    return AgentChatResponse(
        reply=clean_reply,
        event_ready=False,
        event_id=event_id,
        event_draft_pending=draft_pending,
    )
