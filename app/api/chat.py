"""
Chat Room API - 聊天室消息管理

功能：
- 获取用户的聊天室列表
- 获取聊天室消息
- 发送消息（@Agent 时自动触发 Agent 回复）
- 关闭聊天室（活动结束后）
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.chat import ChatRoom, ChatRoomMember, ChatMessage, ChatRoomVote, PassiveMatchRequest
from app.models.user import User, Agent, AgentMemory
from app.models.event import Event
from app.services.agent_server import agent_server
from app.services.prompt_builder import PromptBuilder
from app.api.schemas import (
    ChatRoomResponse, ChatRoomMemberResponse, MessageCreate, MessageResponse,
    PassiveMatchRequestAction, PassiveMatchRequestResponse, VoteRequest, VoteStatusResponse,
)
from app.api.chat_helpers import room_event_ids
from app.api.ws import manager as ws_manager
from app.services.push_notification_service import push_notification_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


async def _broadcast_message_to_room(room_id: UUID, msg: ChatMessage, db: AsyncSession):
    """通过 WebSocket 向聊天室所有 user 成员广播新消息"""
    members_r = await db.execute(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.role == "user",
        )
    )
    user_ids = [str(m.user_id) for m in members_r.scalars().all()]
    payload = {
        "type": "new_message",
        "room_id": str(room_id),
        "message": {
            "id": str(msg.id),
            "room_id": str(msg.room_id),
            "sender_id": str(msg.sender_id),
            "sender_type": msg.sender_type,
            "content": msg.content,
            "mentions": msg.mentions,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        },
    }
    await ws_manager.broadcast_to_users(user_ids, payload)


async def _push_message_to_room(
    room_id: UUID,
    msg: ChatMessage,
    db: AsyncSession,
    *,
    exclude_user_ids: set[UUID] | None = None,
) -> None:
    members_r = await db.execute(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.role == "user",
        )
    )
    exclude_user_ids = exclude_user_ids or set()
    user_ids = [
        member.user_id
        for member in members_r.scalars().all()
        if member.user_id not in exclude_user_ids
    ]
    if not user_ids:
        return

    room_title = await _room_push_title(room_id, db)
    sender_name = await _message_sender_name(msg, db)
    content = _truncate_push_text(msg.content)
    title = room_title
    if sender_name:
        title = f"{sender_name} · {room_title}"
    body = content or "有一条新消息"

    await push_notification_service.send_to_users(
        db,
        user_ids,
        title=title,
        body=body,
        data={
            "type": "new_message",
            "room_id": str(room_id),
            "message_id": str(msg.id),
        },
    )


async def _room_push_title(room_id: UUID, db: AsyncSession) -> str:
    room_r = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = room_r.scalar_one_or_none()
    if room and room.event_id_a:
        event_r = await db.execute(select(Event).where(Event.id == room.event_id_a))
        event = event_r.scalar_one_or_none()
        if event and event.title:
            return event.title
    return "聊天室"


async def _message_sender_name(msg: ChatMessage, db: AsyncSession) -> str:
    if msg.sender_type == "system":
        return "系统"
    if msg.sender_type == "agent":
        agent_r = await db.execute(select(Agent).where(Agent.user_id == msg.sender_id))
        agent = agent_r.scalar_one_or_none()
        return agent.name if agent else "AI"
    user_r = await db.execute(select(User).where(User.id == msg.sender_id))
    user = user_r.scalar_one_or_none()
    return user.name if user else "用户"


def _truncate_push_text(text: str, limit: int = 90) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def _format_room_event_context(event: Event | None, label: str, self_user_id: UUID) -> str:
    """Format one public event for room-agent context."""
    if not event:
        return f"{label}: 未找到事件"

    side = "你这边" if event.user_id == self_user_id else "对方"
    preferences = "、".join(event.preferences or []) if event.preferences else "无"
    constraints = "、".join(event.constraints or []) if event.constraints else "无"
    start_time = event.start_time.isoformat() if event.start_time else "null"
    end_time = event.end_time.isoformat() if event.end_time else "null"
    return (
        f"{label}（{side}）: "
        f"title={event.title}; "
        f"activity_type={event.activity_type}; "
        f"city={event.city or '未填写'}; "
        f"location={event.location or 'null'}; "
        f"start_time={start_time}; "
        f"end_time={end_time}; "
        f"preferences={preferences}; "
        f"constraints={constraints}"
    )


def _extract_room_agent_reply(raw_reply: str) -> str:
    """Room agent prompts return JSON; fall back to raw text for robustness."""
    text = raw_reply.strip()
    if text.startswith("{") or text.startswith("```") or ('"reply"' in text and "{" in text):
        parsed = agent_server.extract_json(text)
        if isinstance(parsed, dict):
            reply = parsed.get("reply")
            if isinstance(reply, str) and reply.strip():
                return reply.strip()
    return text


async def _room_agent_reply(messages: list[dict[str, str]]) -> str:
    raw_reply = ""
    async for piece in agent_server.stream_chat(
        messages,
        purpose="conversation",
        max_tokens=300,
    ):
        raw_reply += piece
    return _extract_room_agent_reply(raw_reply)


def _chat_room_member_response(member: ChatRoomMember, user: User | None = None, agent: Agent | None = None) -> ChatRoomMemberResponse:
    if member.role == "agent":
        return ChatRoomMemberResponse(
            user_id=member.user_id,
            name=agent.name if agent else "Agent",
            role="agent",
            emoji=agent.emoji if agent else None,
            avatar_url=agent.avatar_url if agent else None,
        )
    return ChatRoomMemberResponse(
        user_id=member.user_id,
        name=user.name if user else "用户",
        role="user",
        # Backward-compatible: older clients read only emoji.
        emoji=user.avatar_url if user else None,
        avatar_url=user.avatar_url if user else None,
    )


@router.get("/rooms", response_model=list[ChatRoomResponse])
async def list_my_rooms(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取我的聊天室列表（含成员和事件信息）"""
    # 查找用户参与的聊天室
    result = await db.execute(
        select(ChatRoom)
        .join(ChatRoomMember, ChatRoomMember.room_id == ChatRoom.id)
        .where(ChatRoomMember.user_id == user_id, ChatRoomMember.role == "user")
        .order_by(ChatRoom.created_at.desc())
    )
    rooms = result.scalars().all()

    response = []
    for room in rooms:
        # 加载事件标题
        event_title = None
        if room.event_id_a:
            ev_r = await db.execute(select(Event).where(Event.id == room.event_id_a))
            ev = ev_r.scalar_one_or_none()
            if ev:
                event_title = ev.title

        # 加载成员列表
        members_r = await db.execute(
            select(ChatRoomMember).where(ChatRoomMember.room_id == room.id)
        )
        members = []
        for m in members_r.scalars().all():
            if m.role == "agent":
                agent_r = await db.execute(select(Agent).where(Agent.id == m.agent_id))
                agent = agent_r.scalar_one_or_none()
                members.append(_chat_room_member_response(m, agent=agent))
            else:
                user_r = await db.execute(select(User).where(User.id == m.user_id))
                user = user_r.scalar_one_or_none()
                members.append(_chat_room_member_response(m, user=user))

        # 加载最新一条消息
        last_msg_r = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.room_id == room.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        last_msg = last_msg_r.scalar_one_or_none()

        response.append(ChatRoomResponse(
            id=room.id,
            event_title=event_title,
            match_summary=room.match_summary,
            is_active=room.is_active,
            created_at=room.created_at,
            closed_at=room.closed_at,
            members=members,
            last_message=MessageResponse.model_validate(last_msg) if last_msg else None,
        ))

    return response


@router.get("/match-requests", response_model=list[PassiveMatchRequestResponse])
async def list_match_requests(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取需要我确认的被动匹配请求。"""
    result = await db.execute(
        select(PassiveMatchRequest)
        .where(PassiveMatchRequest.target_user_id == user_id)
        .order_by(PassiveMatchRequest.created_at.desc())
    )
    requests = result.scalars().all()
    response = []
    for req in requests:
        event_r = await db.execute(select(Event).where(Event.id == req.event_id))
        event = event_r.scalar_one_or_none()
        requester_r = await db.execute(select(User).where(User.id == req.requester_user_id))
        requester = requester_r.scalar_one_or_none()
        response.append(PassiveMatchRequestResponse(
            id=req.id,
            event_id=req.event_id,
            event_title=event.title if event else "活动",
            requester_name=requester.name if requester else "用户",
            target_user_id=req.target_user_id,
            status=req.status,
            similarity=req.similarity,
            message=req.message,
            created_at=req.created_at,
        ))
    return response


@router.post("/match-requests/{request_id}/respond")
async def respond_match_request(
    request_id: UUID,
    data: PassiveMatchRequestAction,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """确认或拒绝被动匹配请求。接受后才创建聊天室。"""
    from app.services.passive_matching_service import passive_matching_service

    try:
        return await passive_matching_service.respond_to_request(request_id, user_id, data.action, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/rooms/{room_id}/messages", response_model=list[MessageResponse])
async def get_room_messages(
    room_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    before_id: UUID | None = None,
):
    """获取聊天室消息（分页）"""
    # 验证是聊天室成员
    member = await db.execute(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.role == "user",
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="你不是该聊天室成员")

    query = (
        select(ChatMessage)
        .where(ChatMessage.room_id == room_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )

    if before_id:
        # 获取 before_id 的 created_at 用于分页
        ref = await db.execute(select(ChatMessage).where(ChatMessage.id == before_id))
        ref_msg = ref.scalar_one_or_none()
        if ref_msg:
            query = query.where(ChatMessage.created_at < ref_msg.created_at)

    result = await db.execute(query)
    messages = list(reversed(result.scalars().all()))
    return messages


@router.post("/rooms/{room_id}/messages", response_model=MessageResponse)
async def send_message(
    room_id: UUID,
    data: MessageCreate,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """发送消息到聊天室"""
    # 验证是聊天室成员
    member_r = await db.execute(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.role == "user",
        )
    )
    member = member_r.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="你不是该聊天室成员")

    # 检查聊天室是否活跃
    room_r = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = room_r.scalar_one_or_none()
    if not room or not room.is_active:
        raise HTTPException(status_code=400, detail="聊天室已关闭")

    # 保存消息
    msg = ChatMessage(
        room_id=room_id,
        sender_id=user_id,
        sender_type="user",
        content=data.content,
        mentions=data.mentions,
    )
    db.add(msg)
    await db.flush()

    # WebSocket 广播消息给聊天室成员
    await _broadcast_message_to_room(room_id, msg, db)
    try:
        await _push_message_to_room(room_id, msg, db, exclude_user_ids={user_id})
    except Exception as exc:
        logger.warning("Message saved but push notification failed for room %s: %s", room_id, exc)

    # 检测 @Agent，触发 Agent 回复
    if data.mentions:
        background_tasks.add_task(
            _handle_agent_mention,
            room_id=room_id,
            user_id=user_id,
            message=data.content,
            mentions=data.mentions,
        )

    return msg


@router.post("/rooms/{room_id}/close")
async def close_room(
    room_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """关闭聊天室"""
    # 验证是房主
    member_r = await db.execute(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.is_owner == True,
        )
    )
    if not member_r.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="只有房主可以关闭聊天室")

    room_r = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = room_r.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="聊天室不存在")

    from datetime import datetime, timezone
    room.is_active = False
    room.closed_at = datetime.now(timezone.utc)

    # 添加系统消息
    close_msg = ChatMessage(
        room_id=room_id,
        sender_id=user_id,
        sender_type="system",
        content="活动已结束，聊天室已关闭。感谢参与！",
    )
    db.add(close_msg)
    await db.flush()

    return {"message": "聊天室已关闭"}


# ── 投票 ──

@router.post("/rooms/{room_id}/vote")
async def submit_vote(
    room_id: UUID,
    data: VoteRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """投票：搭(da) 或 不搭(bu_da)"""
    if data.vote not in ("da", "bu_da"):
        raise HTTPException(status_code=400, detail="vote 必须是 da 或 bu_da")

    # 验证是聊天室成员
    member_r = await db.execute(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.role == "user",
        )
    )
    if not member_r.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="你不是该聊天室成员")

    # 检查是否已投票
    existing_r = await db.execute(
        select(ChatRoomVote).where(
            ChatRoomVote.room_id == room_id,
            ChatRoomVote.user_id == user_id,
        )
    )
    if existing_r.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="你已经投过票了")

    # 保存投票
    vote = ChatRoomVote(room_id=room_id, user_id=user_id, vote=data.vote)
    db.add(vote)
    await db.flush()

    # 处理投票结果
    from datetime import datetime, timezone, timedelta
    if data.vote == "bu_da":
        # 任一方不搭 → 关闭聊天室
        room_r = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
        room = room_r.scalar_one_or_none()
        if room:
            room.is_active = False
            room.closed_at = datetime.now(timezone.utc)

            # 系统消息
            close_msg = ChatMessage(
                room_id=room_id,
                sender_id=user_id,
                sender_type="system",
                content="有人选择了「不搭」，聊天室已关闭。",
            )
            db.add(close_msg)
            await db.flush()
            await _broadcast_message_to_room(room_id, close_msg, db)
            await _push_message_to_room(room_id, close_msg, db)

            # 事件回退
            await _handle_vote_rejection(room, db)

        # WebSocket 通知
        await ws_manager.broadcast_to_users(
            [str(user_id)],
            {"type": "vote_result", "room_id": str(room_id), "result": "rejected"},
        )
    else:
        # 检查对方是否也投了搭
        all_votes_r = await db.execute(
            select(ChatRoomVote).where(ChatRoomVote.room_id == room_id)
        )
        all_votes = all_votes_r.scalars().all()
        if len(all_votes) == 2 and all(v.vote == "da" for v in all_votes):
            # 双方都搭 → 事件确认
            room_r = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
            room = room_r.scalar_one_or_none()
            if room:
                for event_id in room_event_ids(room):
                    ev_r = await db.execute(select(Event).where(Event.id == event_id))
                    ev = ev_r.scalar_one_or_none()
                    if ev:
                        ev.status = "active"

            # 系统消息
            match_msg = ChatMessage(
                room_id=room_id,
                sender_id=user_id,
                sender_type="system",
                content="双方都选择了「搭」！活动确认，祝你们玩得开心！🎉",
            )
            db.add(match_msg)
            await db.flush()
            await _broadcast_message_to_room(room_id, match_msg, db)
            await _push_message_to_room(room_id, match_msg, db)

            # 通知双方
            members_r = await db.execute(
                select(ChatRoomMember).where(
                    ChatRoomMember.room_id == room_id,
                    ChatRoomMember.role == "user",
                )
            )
            member_ids = [str(m.user_id) for m in members_r.scalars().all()]
            await ws_manager.broadcast_to_users(
                member_ids,
                {"type": "vote_result", "room_id": str(room_id), "result": "matched"},
            )

    return {"message": "投票成功", "vote": data.vote}


@router.get("/rooms/{room_id}/vote-status", response_model=VoteStatusResponse)
async def get_vote_status(
    room_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取聊天室投票状态"""
    # 验证是聊天室成员
    member_r = await db.execute(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.role == "user",
        )
    )
    if not member_r.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="你不是该聊天室成员")

    # 查询所有投票
    votes_r = await db.execute(
        select(ChatRoomVote).where(ChatRoomVote.room_id == room_id)
    )
    votes = votes_r.scalars().all()

    my_vote = None
    partner_vote = None
    for v in votes:
        if v.user_id == user_id:
            my_vote = v.vote
        else:
            partner_vote = v.vote

    # 计算结果
    result = "pending"
    if my_vote == "bu_da" or partner_vote == "bu_da":
        result = "rejected"
    elif my_vote == "da" and partner_vote == "da":
        result = "matched"

    return VoteStatusResponse(my_vote=my_vote, partner_vote=partner_vote, result=result)


async def _handle_vote_rejection(room: ChatRoom, db: AsyncSession):
    """处理不搭后的事件回退"""
    from datetime import datetime, timezone, timedelta
    from app.services.match_blocklist_service import add_match_blocklist
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    events_by_id = {}

    for event_id in room_event_ids(room):
        ev_r = await db.execute(select(Event).where(Event.id == event_id))
        ev = ev_r.scalar_one_or_none()
        if ev:
            events_by_id[event_id] = ev

    if room.event_id_a and room.event_id_b and room.event_id_a in events_by_id and room.event_id_b in events_by_id:
        event_a = events_by_id[room.event_id_a]
        event_b = events_by_id[room.event_id_b]
        await add_match_blocklist(
            db,
            event_a_id=event_a.id,
            event_b_id=event_b.id,
            user_a_id=event_a.user_id,
            user_b_id=event_b.user_id,
            reason="vote_rejected",
            source_room_id=room.id,
        )

    if room.event_id_a:
        ev = events_by_id.get(room.event_id_a)
        if ev and ev.status == "matched":
            if ev.start_time and ev.start_time <= tomorrow:
                ev.status = "cancelled"
            else:
                ev.status = "pending"
                ev.matched_event_id = None
                ev.match_score = None
                ev.match_round = (ev.match_round or 0) + 1

    if room.event_id_b:
        ev = events_by_id.get(room.event_id_b)
        if ev and ev.status == "matched":
            if ev.start_time and ev.start_time <= tomorrow:
                ev.status = "cancelled"
            else:
                ev.status = "pending"
                ev.matched_event_id = None
                ev.match_score = None
                ev.match_round = (ev.match_round or 0) + 1


# ── 后台任务 ──

async def _handle_agent_mention(
    room_id: UUID,
    user_id: UUID,
    message: str,
    mentions: list[str],
):
    """处理 @Agent 提及，生成 Agent 回复"""
    from app.core.database import async_session

    try:
        async with async_session() as db:
            # 通过聊天室成员表查找被 @ 的 Agent（避免全局同名问题）
            agent_members_r = await db.execute(
                select(ChatRoomMember).where(
                    ChatRoomMember.room_id == room_id,
                    ChatRoomMember.role == "agent",
                )
            )
            agent_members = agent_members_r.scalars().all()

            for am in agent_members:
                agent_r = await db.execute(select(Agent).where(Agent.id == am.agent_id))
                agent = agent_r.scalar_one_or_none()
                if not agent or agent.name not in mentions:
                    continue

                # 加载 Agent 的用户
                user_r = await db.execute(select(User).where(User.id == agent.user_id))
                owner = user_r.scalar_one_or_none()
                if not owner:
                    continue

                # 加载聊天室信息
                room_r = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
                room = room_r.scalar_one_or_none()
                if not room:
                    continue

                # 加载发送者信息
                sender_r = await db.execute(select(User).where(User.id == user_id))
                sender = sender_r.scalar_one_or_none()
                sender_name = sender.name if sender else "用户"

                # 加载最近消息作为上下文
                recent_r = await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.room_id == room_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(10)
                )
                recent = list(reversed(recent_r.scalars().all()))
                recent_messages_text = "\n".join([f"{m.sender_type}: {m.content}" for m in recent])

                # 获取双方公开事件；两边 agent 都能看到事件，但只能看到自己的 memory
                event_a = None
                event_b = None
                if room.event_id_a:
                    ev_a_r = await db.execute(select(Event).where(Event.id == room.event_id_a))
                    event_a = ev_a_r.scalar_one_or_none()
                if room.event_id_b:
                    ev_b_r = await db.execute(select(Event).where(Event.id == room.event_id_b))
                    event_b = ev_b_r.scalar_one_or_none()

                event_titles = [ev.title for ev in (event_a, event_b) if ev]
                event_title = " / ".join(event_titles) if event_titles else "活动"
                public_events_text = "\n".join([
                    _format_room_event_context(event_a, "A", agent.user_id),
                    _format_room_event_context(event_b, "B", agent.user_id),
                ])

                # 查询 Agent 所属用户的记忆
                mem_r = await db.execute(
                    select(AgentMemory)
                    .where(AgentMemory.user_id == agent.user_id, AgentMemory.is_active == True)
                    .order_by(AgentMemory.updated_at.desc())
                    .limit(20)
                )
                user_memories = [(m.type, m.content) for m in mem_r.scalars().all()]

                # 查询聊天室参与者名单
                participants_r = await db.execute(
                    select(ChatRoomMember).where(ChatRoomMember.room_id == room_id)
                )
                participant_names = []
                for mem in participants_r.scalars().all():
                    if mem.role == "agent":
                        ag_r = await db.execute(select(Agent).where(Agent.id == mem.agent_id))
                        ag = ag_r.scalar_one_or_none()
                        participant_names.append(f"{ag.name}(Agent)" if ag else "Agent")
                    else:
                        u_r = await db.execute(select(User).where(User.id == mem.user_id))
                        u = u_r.scalar_one_or_none()
                        participant_names.append(u.name if u else "用户")

                # 构建 prompt
                system_prompt = PromptBuilder.build_room_agent_reply_prompt(
                    agent_name=agent.name,
                    agent_personality=agent.personality or "",
                    user_name=owner.name,
                    event_title=event_title,
                    match_summary=room.match_summary or "",
                    mentioned_by=sender_name,
                    user_memories=user_memories,
                    participants=participant_names,
                    public_events_text=public_events_text,
                    agent_dialogue=room.agent_dialogue or "",
                    recent_messages_text=recent_messages_text,
                )

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请回复这次 @{agent.name} 的消息，只返回 JSON。"},
                ]

                reply = await _room_agent_reply(messages)

                # 保存 Agent 回复（sender_id FK 指向 users.id，用 agent 所属用户的 ID）
                agent_msg = ChatMessage(
                    room_id=room_id,
                    sender_id=agent.user_id,
                    sender_type="agent",
                    content=reply,
                )
                db.add(agent_msg)
                await db.flush()

                # WebSocket 广播 Agent 回复
                await _broadcast_message_to_room(room_id, agent_msg, db)
                await _push_message_to_room(room_id, agent_msg, db)

            await db.commit()

    except Exception as e:
        logger.error(f"Agent mention reply failed: {e}")
