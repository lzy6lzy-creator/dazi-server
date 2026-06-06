"""
Admin API - 管理后台接口

手动触发匹配、查看系统状态、批量操作
需要 Bearer Token 认证
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select, func, delete

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User, Agent, AgentMemory, AgentChatMessage
from app.models.event import Event, MatchLog, MatchBlocklist
from app.models.chat import ChatRoom, ChatRoomMember, ChatMessage
from app.models.beta_signup import BetaSignup
from app.models.site_feedback import SiteFeedback
from app.services.app_store_connect import (
    AppStoreConnectClient,
    AppStoreConnectConfigError,
    AppStoreConnectError,
)

from app.core.log_buffer import log_buffer

logger = logging.getLogger(__name__)

security_scheme = HTTPBearer(auto_error=False)


async def verify_admin(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
    if not credentials or credentials.credentials != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin access denied")


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(verify_admin)])

BETA_SIGNUP_STATUSES = {"new", "updated", "approved", "invited", "accepted", "rejected", "archived"}
FEEDBACK_STATUSES = {"new", "reviewed", "resolved", "archived"}


class BetaSignupStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1, max_length=30)


class FeedbackStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1, max_length=30)


def append_internal_test_phone(phone: str | None, *, name: str, email: str) -> str:
    if not phone:
        return "missing"
    phones_path = Path(settings.INTERNAL_TEST_PHONES_FILE)
    try:
        phones_path.parent.mkdir(parents=True, exist_ok=True)
        existing = phones_path.read_text(encoding="utf-8") if phones_path.exists() else ""
        if phone in existing:
            return "already_present"
        with phones_path.open("a", encoding="utf-8") as file:
            if existing and not existing.endswith("\n"):
                file.write("\n")
            file.write(f"{phone}  # {name} {email} TestFlight internal invite\n")
        return "added"
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写入内测手机号白名单失败: {exc}") from exc


def admin_event_detail_payload(event: Event, user: User | None = None) -> dict:
    return {
        "id": str(event.id),
        "user_id": str(event.user_id),
        "user_name": user.name if user else None,
        "title": event.title,
        "activity_type": event.activity_type,
        "status": event.status,
        "city": event.city,
        "city_normalized": event.city_normalized,
        "location": event.location,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "end_time": event.end_time.isoformat() if event.end_time else None,
        "preferences": event.preferences or [],
        "constraints": event.constraints or [],
        "match_score": float(event.match_score) if event.match_score else None,
        "matched_event_id": str(event.matched_event_id) if event.matched_event_id else None,
        "created_at": event.created_at.isoformat(),
    }


# ── 系统状态 ──

@router.get("/status")
async def system_status(db: AsyncSession = Depends(get_db)):
    """查看系统整体状态"""
    users = await db.execute(select(func.count(User.id)))
    agents = await db.execute(select(func.count(Agent.id)))
    events = await db.execute(select(func.count(Event.id)))
    pending = await db.execute(select(func.count(Event.id)).where(Event.status == "pending"))
    matching = await db.execute(select(func.count(Event.id)).where(Event.status == "matching"))
    matched = await db.execute(select(func.count(Event.id)).where(Event.status == "matched"))
    memories = await db.execute(select(func.count(AgentMemory.id)))
    chat_msgs = await db.execute(select(func.count(AgentChatMessage.id)))
    rooms = await db.execute(select(func.count(ChatRoom.id)))
    beta_signups = await db.execute(select(func.count(BetaSignup.id)))
    feedback = await db.execute(select(func.count(SiteFeedback.id)))

    return {
        "users": users.scalar(),
        "agents": agents.scalar(),
        "events": {
            "total": events.scalar(),
            "pending": pending.scalar(),
            "matching": matching.scalar(),
            "matched": matched.scalar(),
        },
        "memories": memories.scalar(),
        "agent_chat_messages": chat_msgs.scalar(),
        "chat_rooms": rooms.scalar(),
        "beta_signups": beta_signups.scalar(),
        "feedback": feedback.scalar(),
    }


# ── 查看所有用户 ──

@router.get("/users")
async def list_all_users(db: AsyncSession = Depends(get_db)):
    """查看所有用户及其 Agent"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    data = []
    for u in users:
        agent_r = await db.execute(select(Agent).where(Agent.user_id == u.id))
        agent = agent_r.scalar_one_or_none()

        events_r = await db.execute(
            select(Event).where(Event.user_id == u.id).order_by(Event.created_at.desc())
        )
        events = events_r.scalars().all()

        mems_r = await db.execute(
            select(AgentMemory).where(AgentMemory.user_id == u.id, AgentMemory.is_active == True)
        )
        mems = mems_r.scalars().all()

        data.append({
            "id": str(u.id),
            "name": u.name,
            "phone": u.phone,
            "city": u.city,
            "interests": u.interests,
            "agent": {
                "name": agent.name if agent else None,
                "personality": agent.personality if agent else None,
            } if agent else None,
            "events": [
                {
                    "id": str(e.id),
                    "title": e.title,
                    "activity_type": e.activity_type,
                    "status": e.status,
                    "match_score": float(e.match_score) if e.match_score else None,
                    "matched_event_id": str(e.matched_event_id) if e.matched_event_id else None,
                }
                for e in events
            ],
            "memories": [
                {"type": m.type, "content": m.content, "confidence": m.confidence}
                for m in mems
            ],
        })

    return data


# ── 查看所有事件 ──

@router.get("/events")
async def list_all_events(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """查看所有事件（可按状态过滤）"""
    query = select(Event).order_by(Event.created_at.desc())
    if status:
        query = query.where(Event.status == status)

    result = await db.execute(query)
    events = result.scalars().all()

    data = []
    for e in events:
        user_r = await db.execute(select(User).where(User.id == e.user_id))
        user = user_r.scalar_one_or_none()
        data.append({
            "id": str(e.id),
            "user_name": user.name if user else "unknown",
            "title": e.title,
            "activity_type": e.activity_type,
            "start_time": e.start_time.isoformat() if e.start_time else None,
            "location": e.location,
            "city": e.city,
            "preferences": e.preferences,
            "constraints": e.constraints,
            "status": e.status,
            "match_score": float(e.match_score) if e.match_score else None,
            "matched_event_id": str(e.matched_event_id) if e.matched_event_id else None,
            "created_at": e.created_at.isoformat(),
        })

    return data


# ── 匹配预览（查看评分详情，不执行匹配） ──

@router.get("/match/preview/{event_id}")
async def preview_match(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """查看事件的匹配候选 top10 评分详情（不执行匹配）"""
    from app.services.matching_service import matching_service
    return await matching_service.preview_match(event_id, db)


@router.get("/match/detail/{event_id}/{candidate_id}")
async def match_pair_detail(
    event_id: UUID,
    candidate_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """查看一对候选事件的 A2A 对话、日志、打分和黑名单记录。"""
    event = await db.get(Event, event_id)
    candidate = await db.get(Event, candidate_id)
    if not event or not candidate:
        raise HTTPException(status_code=404, detail="事件或候选事件不存在")

    users_r = await db.execute(
        select(User).where(User.id.in_({event.user_id, candidate.user_id}))
    )
    users_by_id = {user.id: user for user in users_r.scalars().all()}

    pair_filter = or_(
        (MatchLog.event_a_id == event_id) & (MatchLog.event_b_id == candidate_id),
        (MatchLog.event_a_id == candidate_id) & (MatchLog.event_b_id == event_id),
    )
    logs_r = await db.execute(
        select(MatchLog)
        .where(pair_filter)
        .order_by(MatchLog.created_at.desc())
    )
    logs = [
        {
            "id": str(log.id),
            "event_a_id": str(log.event_a_id),
            "event_b_id": str(log.event_b_id),
            "stage": log.stage,
            "score": float(log.score or 0),
            "reasons": log.reasons or [],
            "issues": log.issues or [],
            "score_breakdown": log.score_breakdown or [],
            "dialogue_log": log.dialogue_log,
            "result": log.result,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs_r.scalars().all()
    ]

    blocklist_r = await db.execute(
        select(MatchBlocklist)
        .where(
            or_(
                (MatchBlocklist.event_a_id == event_id) & (MatchBlocklist.event_b_id == candidate_id),
                (MatchBlocklist.event_a_id == candidate_id) & (MatchBlocklist.event_b_id == event_id),
            )
        )
        .order_by(MatchBlocklist.created_at.desc())
    )
    blocklists = [
        {
            "id": str(row.id),
            "event_a_id": str(row.event_a_id) if row.event_a_id else None,
            "event_b_id": str(row.event_b_id) if row.event_b_id else None,
            "user_a_id": str(row.user_a_id),
            "user_b_id": str(row.user_b_id),
            "reason": row.reason,
            "source_room_id": str(row.source_room_id) if row.source_room_id else None,
            "source_request_id": str(row.source_request_id) if row.source_request_id else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in blocklist_r.scalars().all()
    ]

    rooms_r = await db.execute(
        select(ChatRoom)
        .where(
            or_(
                (ChatRoom.event_id_a == event_id) & (ChatRoom.event_id_b == candidate_id),
                (ChatRoom.event_id_a == candidate_id) & (ChatRoom.event_id_b == event_id),
            )
        )
        .order_by(ChatRoom.created_at.desc())
    )
    rooms = [
        {
            "id": str(room.id),
            "event_id_a": str(room.event_id_a) if room.event_id_a else None,
            "event_id_b": str(room.event_id_b) if room.event_id_b else None,
            "match_type": room.match_type,
            "match_summary": room.match_summary,
            "is_active": room.is_active,
            "created_at": room.created_at.isoformat(),
        }
        for room in rooms_r.scalars().all()
    ]

    latest_a2a = next((log for log in logs if log["stage"].startswith("a2a")), None)
    latest_log = logs[0] if logs else None

    return {
        "event": admin_event_detail_payload(event, users_by_id.get(event.user_id)),
        "candidate": admin_event_detail_payload(candidate, users_by_id.get(candidate.user_id)),
        "summary": {
            "log_count": len(logs),
            "latest_stage": latest_log["stage"] if latest_log else None,
            "latest_score": latest_log["score"] if latest_log else None,
            "latest_result": latest_log["result"] if latest_log else None,
            "a2a_score": latest_a2a["score"] if latest_a2a else None,
            "a2a_result": latest_a2a["result"] if latest_a2a else None,
            "blocklisted": bool(blocklists),
            "room_count": len(rooms),
        },
        "logs": logs,
        "latest_a2a": latest_a2a,
        "blocklists": blocklists,
        "rooms": rooms,
    }


# ── 手动触发：单个事件匹配 ──

@router.post("/match/event/{event_id}")
async def trigger_single_match(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """手动触发单个事件的匹配"""
    from app.services.matching_service import matching_service

    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "事件不存在"}
    if event.status != "pending":
        return {"error": f"事件状态为 {event.status}，只有 pending 状态可匹配"}

    match_result = await matching_service.match_event(event_id, db)
    await db.commit()

    if match_result:
        return {
            "success": True,
            "matched_event_id": str(match_result["matched_event_id"]),
            "score": match_result["score"],
            "reasons": match_result["reasons"],
            "chat_room_id": match_result.get("chat_room_id"),
        }
    else:
        return {"success": False, "message": "未找到合适的匹配"}


# ── 手动强制匹配：指定两个事件 ──

@router.post("/match/manual")
async def manual_match(
    event_id_a: str,
    event_id_b: str,
    db: AsyncSession = Depends(get_db),
):
    """手动强制匹配两个事件，跳过过滤，直接 A2A 对话并创建聊天室"""
    from app.services.matching_service import matching_service

    try:
        result = await matching_service.force_match(
            UUID(event_id_a), UUID(event_id_b), db
        )
        await db.commit()
        return {"success": True, **result}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"匹配失败: {str(e)}"}


# ── 手动触发：全量匹配（所有 pending 事件） ──

@router.post("/match/all")
async def trigger_match_all(db: AsyncSession = Depends(get_db)):
    """
    对所有 pending 状态的事件执行匹配

    模拟生产环境的定时批量匹配
    """
    from app.services.matching_service import matching_service

    result = await db.execute(
        select(Event).where(Event.status == "pending").order_by(Event.created_at.asc())
    )
    pending_events = result.scalars().all()

    if not pending_events:
        return {"message": "没有 pending 状态的事件", "matched": 0}

    results = []
    for event in pending_events:
        # 重新检查状态（可能在本轮匹配中已被配对）
        refreshed = await db.execute(select(Event).where(Event.id == event.id))
        current = refreshed.scalar_one_or_none()
        if not current or current.status != "pending":
            continue

        try:
            match_result = await matching_service.match_event(event.id, db)
            await db.commit()

            if match_result:
                results.append({
                    "event_id": str(event.id),
                    "event_title": event.title,
                    "matched_event_id": str(match_result["matched_event_id"]),
                    "score": match_result["score"],
                    "chat_room_id": match_result.get("chat_room_id"),
                })
        except Exception as e:
            logger.error(f"Match failed for event {event.id}: {e}")
            results.append({
                "event_id": str(event.id),
                "event_title": event.title,
                "error": str(e),
            })

    return {
        "total_pending": len(pending_events),
        "matched": len([r for r in results if "matched_event_id" in r]),
        "results": results,
    }


# ── 手动触发定时匹配（后台执行） ──

@router.post("/match/run-all")
async def run_scheduled_matching():
    """手动触发一次全量匹配（等同于定时任务），后台异步执行"""
    from app.services.scheduler import match_scheduler
    asyncio.create_task(match_scheduler._run_matching())
    return {"message": "全量匹配已触发，后台执行中，请查看日志了解进度"}


# ── 手动重置事件状态 ──

@router.post("/events/{event_id}/reset")
async def reset_event_status(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """将事件重置为 pending 状态（方便反复测试）"""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "事件不存在"}

    old_status = event.status
    event.status = "pending"
    event.matched_event_id = None
    event.match_score = None
    event.match_round = 0
    await db.execute(
        delete(MatchBlocklist).where(
            or_(
                MatchBlocklist.event_a_id == event_id,
                MatchBlocklist.event_b_id == event_id,
            )
        )
    )
    await db.flush()

    return {
        "message": f"事件已从 {old_status} 重置为 pending",
        "event_id": str(event_id),
    }


# ── 手动重置所有事件 ──

@router.post("/events/reset-all")
async def reset_all_events(db: AsyncSession = Depends(get_db)):
    """将所有非 cancelled 事件重置为 pending"""
    result = await db.execute(
        select(Event).where(Event.status != "cancelled")
    )
    events = result.scalars().all()
    count = 0
    for e in events:
        e.status = "pending"
        e.matched_event_id = None
        e.match_score = None
        e.match_round = 0
        count += 1
    await db.execute(delete(MatchBlocklist))
    await db.flush()
    return {"message": f"已重置 {count} 个事件为 pending"}


# ── 查看匹配日志 ──

@router.get("/match-logs")
async def get_match_logs(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """查看最近的匹配日志"""
    result = await db.execute(
        select(MatchLog).order_by(MatchLog.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()

    return [
        {
            "id": str(l.id),
            "event_a_id": str(l.event_a_id),
            "event_b_id": str(l.event_b_id),
            "stage": l.stage,
            "score": l.score,
            "reasons": l.reasons,
            "issues": l.issues,
            "score_breakdown": l.score_breakdown or [],
            "result": l.result,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


# ── 查看聊天室详情 ──

@router.get("/rooms")
async def list_all_rooms(db: AsyncSession = Depends(get_db)):
    """查看所有聊天室"""
    result = await db.execute(
        select(ChatRoom).order_by(ChatRoom.created_at.desc())
    )
    rooms = result.scalars().all()

    data = []
    for r in rooms:
        members_r = await db.execute(
            select(ChatRoomMember).where(ChatRoomMember.room_id == r.id)
        )
        members = members_r.scalars().all()

        msgs_r = await db.execute(
            select(func.count(ChatMessage.id)).where(ChatMessage.room_id == r.id)
        )
        msg_count = msgs_r.scalar()

        data.append({
            "id": str(r.id),
            "event_id_a": str(r.event_id_a) if r.event_id_a else None,
            "event_id_b": str(r.event_id_b) if r.event_id_b else None,
            "match_summary": r.match_summary,
            "is_active": r.is_active,
            "member_count": len(members),
            "message_count": msg_count,
            "created_at": r.created_at.isoformat(),
        })

    return data


# ── 日志查看 ──

@router.get("/logs")
async def get_logs(limit: int = 200, level: str | None = None):
    """获取最近的应用日志"""
    return log_buffer.get_logs(limit=limit, level=level)


@router.delete("/logs")
async def clear_logs():
    """清空日志缓冲区"""
    log_buffer.clear()
    return {"message": "日志已清空"}


# ── 内测报名 ──

def beta_signup_payload(signup: BetaSignup) -> dict:
    return {
        "id": str(signup.id),
        "name": signup.name,
        "email": signup.email,
        "contact": signup.contact,
        "city": signup.city,
        "device": signup.device,
        "activity_interests": signup.activity_interests or [],
        "note": signup.note,
        "source": signup.source,
        "status": signup.status,
        "ip_address": signup.ip_address,
        "created_at": signup.created_at.isoformat(),
        "updated_at": signup.updated_at.isoformat(),
    }


def beta_signup_query(status: str | None = None, q: str | None = None):
    query = select(BetaSignup)
    if status:
        query = query.where(BetaSignup.status == status)
    if q and q.strip():
        pattern = f"%{q.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(BetaSignup.name).like(pattern),
                func.lower(BetaSignup.email).like(pattern),
                func.lower(BetaSignup.contact).like(pattern),
                func.lower(BetaSignup.city).like(pattern),
                func.lower(BetaSignup.device).like(pattern),
            )
        )
    return query.order_by(BetaSignup.created_at.desc())


@router.get("/beta-signups")
async def list_beta_signups(
    status: str | None = None,
    q: str | None = None,
    limit: int = 300,
    db: AsyncSession = Depends(get_db),
):
    """查看官网内测报名。"""
    safe_limit = max(1, min(limit, 1000))
    result = await db.execute(beta_signup_query(status=status, q=q).limit(safe_limit))
    return [beta_signup_payload(signup) for signup in result.scalars().all()]


@router.patch("/beta-signups/{signup_id}/status")
async def update_beta_signup_status(
    signup_id: UUID,
    body: BetaSignupStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """手动记录内测报名处理状态。"""
    status = body.status.strip().lower()
    if status not in BETA_SIGNUP_STATUSES:
        raise HTTPException(status_code=400, detail=f"不支持的内测报名状态: {status}")

    result = await db.execute(select(BetaSignup).where(BetaSignup.id == signup_id))
    signup = result.scalar_one_or_none()
    if not signup:
        raise HTTPException(status_code=404, detail="内测报名不存在")

    signup.status = status
    signup.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return beta_signup_payload(signup)


@router.post("/beta-signups/{signup_id}/invite-internal")
async def invite_beta_signup_internal(
    signup_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """一键发起内部测试邀请。需要 ASC_KEY_ID/ASC_ISSUER_ID/ASC_PRIVATE_KEY_PATH。"""
    result = await db.execute(select(BetaSignup).where(BetaSignup.id == signup_id))
    signup = result.scalar_one_or_none()
    if not signup:
        raise HTTPException(status_code=404, detail="内测报名不存在")

    phone_status = append_internal_test_phone(signup.contact, name=signup.name, email=signup.email)
    try:
        asc_result = await AppStoreConnectClient.from_settings(settings).invite_internal_tester(
            email=signup.email,
            name=signup.name,
        )
    except AppStoreConnectConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except AppStoreConnectError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    signup.status = "invited"
    signup.updated_at = datetime.now(timezone.utc)
    await db.flush()
    payload = beta_signup_payload(signup)
    payload["phone_status"] = phone_status
    payload["app_store_connect"] = asc_result
    return payload


@router.get("/beta-signups.csv")
async def export_beta_signups_csv(
    status: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """导出官网内测报名，方便整理 TestFlight 邀请邮箱。"""
    result = await db.execute(beta_signup_query(status=status, q=q))
    signups = result.scalars().all()

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "Apple ID 邮箱",
        "姓名/昵称",
        "微信/手机号",
        "城市",
        "设备",
        "想参加的活动",
        "备注",
        "状态",
        "来源",
        "报名时间",
    ])
    for signup in signups:
        writer.writerow([
            signup.email,
            signup.name,
            signup.contact or "",
            signup.city or "",
            signup.device or "",
            "、".join(signup.activity_interests or []),
            signup.note or "",
            signup.status,
            signup.source,
            signup.created_at.isoformat(),
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dazi-beta-signups.csv"'},
    )


# ── 官网反馈 ──

def feedback_payload(feedback: SiteFeedback) -> dict:
    return {
        "id": str(feedback.id),
        "category": feedback.category,
        "content": feedback.content,
        "contact": feedback.contact,
        "source": feedback.source,
        "status": feedback.status,
        "ip_address": feedback.ip_address,
        "created_at": feedback.created_at.isoformat(),
        "updated_at": feedback.updated_at.isoformat(),
    }


def feedback_query(
    status: str | None = None,
    category: str | None = None,
    q: str | None = None,
):
    query = select(SiteFeedback)
    if status:
        query = query.where(SiteFeedback.status == status)
    if category:
        query = query.where(SiteFeedback.category == category)
    if q and q.strip():
        pattern = f"%{q.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(SiteFeedback.category).like(pattern),
                func.lower(SiteFeedback.content).like(pattern),
                func.lower(SiteFeedback.contact).like(pattern),
                func.lower(SiteFeedback.source).like(pattern),
            )
        )
    return query.order_by(SiteFeedback.created_at.desc())


@router.get("/feedback")
async def list_feedback(
    status: str | None = None,
    category: str | None = None,
    q: str | None = None,
    limit: int = 300,
    db: AsyncSession = Depends(get_db),
):
    """查看官网反馈。"""
    safe_limit = max(1, min(limit, 1000))
    result = await db.execute(feedback_query(status=status, category=category, q=q).limit(safe_limit))
    return [feedback_payload(item) for item in result.scalars().all()]


@router.patch("/feedback/{feedback_id}/status")
async def update_feedback_status(
    feedback_id: UUID,
    body: FeedbackStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """手动记录官网反馈处理状态。"""
    status = body.status.strip().lower()
    if status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail=f"不支持的反馈状态: {status}")

    result = await db.execute(select(SiteFeedback).where(SiteFeedback.id == feedback_id))
    feedback = result.scalar_one_or_none()
    if not feedback:
        raise HTTPException(status_code=404, detail="反馈不存在")

    feedback.status = status
    feedback.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return feedback_payload(feedback)


@router.get("/feedback.csv")
async def export_feedback_csv(
    status: str | None = None,
    category: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """导出官网反馈，方便集中整理。"""
    result = await db.execute(feedback_query(status=status, category=category, q=q))
    feedback_items = result.scalars().all()

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "反馈类型",
        "反馈内容",
        "联系方式",
        "状态",
        "来源",
        "提交时间",
    ])
    for item in feedback_items:
        writer.writerow([
            item.category,
            item.content,
            item.contact or "",
            item.status,
            item.source,
            item.created_at.isoformat(),
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dazi-feedback.csv"'},
    )


# ── 删除用户 ──

# ── 测试数据生成 ──

@router.post("/test/generate")
async def generate_test_data(
    user_count: int = 200,
    events_per_user: int = 5,
    db: AsyncSession = Depends(get_db),
):
    """
    生成大量随机测试用户和事件（用于压测匹配系统）

    默认: 200 用户 × 5 事件 = 1000 事件
    """
    import random
    import asyncio
    from datetime import timedelta
    from app.services.embedding_service import embedding_service

    CITIES = ["上海", "北京", "深圳", "广州", "杭州", "成都", "南京", "武汉"]
    ACTIVITY_TYPES = ["电影", "徒步", "美食", "看展", "咖啡", "桌游", "摄影", "演出", "运动"]
    LOCATIONS_BY_CITY = {
        "上海": ["浦东新区", "静安寺", "徐汇区", "虹口区", "长宁区", "黄浦区", "杨浦区"],
        "北京": ["朝阳区", "海淀区", "东城区", "西城区", "丰台区", "通州区"],
        "深圳": ["南山区", "福田区", "罗湖区", "宝安区", "龙岗区"],
        "广州": ["天河区", "越秀区", "海珠区", "番禺区", "白云区"],
        "杭州": ["西湖区", "拱墅区", "上城区", "滨江区", "余杭区"],
        "成都": ["锦江区", "武侯区", "青羊区", "金牛区", "高新区"],
        "南京": ["玄武区", "秦淮区", "鼓楼区", "建邺区", "江宁区"],
        "武汉": ["武昌区", "江汉区", "洪山区", "汉阳区", "江岸区"],
    }
    PREFS_POOL = {
        "电影": ["科幻片", "文艺片", "喜剧片", "悬疑片", "动作片", "IMAX", "国产片", "日韩片", "动画片"],
        "徒步": ["轻度路线", "中度路线", "重装穿越", "带狗", "拍照", "日出", "野餐"],
        "美食": ["川菜", "粤菜", "日料", "西餐", "火锅", "烧烤", "甜品", "素食", "海鲜"],
        "看展": ["当代艺术", "摄影展", "历史展", "科技展", "互动体验", "免费展"],
        "咖啡": ["精品咖啡", "连锁店", "安静", "拍照好看", "户外座位", "有猫"],
        "桌游": ["狼人杀", "剧本杀", "德式桌游", "卡牌游戏", "新手友好", "重策"],
        "摄影": ["人像", "风光", "街拍", "胶片", "手机摄影", "夜景"],
        "演出": ["livehouse", "音乐节", "话剧", "脱口秀", "相声", "演唱会"],
        "运动": ["羽毛球", "篮球", "游泳", "跑步", "攀岩", "瑜伽", "网球", "飞盘"],
    }
    CONSTRAINTS_POOL = ["不吃辣", "预算100以内", "预算200以内", "不要太远", "有停车位",
                        "不恐高", "室内", "不超过3小时", "周末", "工作日晚上",
                        "不要太吵", "素食", "无烟", "不饮酒", "带小孩"]
    NAMES = ["小明", "小红", "阿强", "小美", "大伟", "小丽", "阿杰", "小敏", "小刚",
             "小芳", "阿飞", "小婷", "小伟", "小慧", "阿龙", "小燕", "小涛", "小琳",
             "阿华", "小雪", "小磊", "小颖", "阿鹏", "小月", "小辉", "小玲", "阿勇",
             "小梅", "小凯", "小莹", "阿峰", "小娟", "小鑫", "小蕾", "阿军", "小静"]
    BIOS = [
        "喜欢探索城市的自由职业者", "周末不想宅在家的程序员", "热爱户外运动的设计师",
        "文艺青年一枚", "社恐但想交朋友", "刚搬到这个城市想认识人",
        "美食博主在找探店搭子", "电影迷找同好", "喜欢安静活动的上班族",
        "运动爱好者找队友", "喜欢拍照的旅行者", "桌游老玩家带新人",
        "音乐发烧友", "咖啡爱好者", "喜欢逛展的学生",
    ]
    GENDERS = ["male", "female"]
    PERSONALITIES = ["贴心、有趣", "理性、高效", "幽默、搞怪", "温柔、细心", "直爽、干脆", "可爱、活泼"]

    now = datetime.now(timezone.utc)
    created_users = 0
    created_events = 0
    all_events = []

    for i in range(user_count):
        city = random.choice(CITIES)
        name = f"{random.choice(NAMES)}{random.randint(1, 999):03d}"
        phone = f"test_{random.randint(10000000000, 99999999999)}"

        user = User(
            phone=phone,
            name=name,
            gender=random.choice(GENDERS),
            birth_year=random.randint(1990, 2003),
            bio=random.choice(BIOS),
            interests=random.sample(ACTIVITY_TYPES, k=random.randint(2, 5)),
            city=city,
        )
        db.add(user)
        await db.flush()

        agent = Agent(
            user_id=user.id,
            name=random.choice(["点点", "圆圆", "小助手", "搭搭", "配配"]),
            personality=random.choice(PERSONALITIES),
        )
        db.add(agent)

        # 为每个用户生成多个事件
        for _ in range(events_per_user):
            act_type = random.choice(ACTIVITY_TYPES)
            prefs = random.sample(PREFS_POOL.get(act_type, []), k=random.randint(1, 3))
            cons = random.sample(CONSTRAINTS_POOL, k=random.randint(0, 2))
            locations = LOCATIONS_BY_CITY.get(city, ["市中心"])
            location = f"{city} {random.choice(locations)}"

            # 随机时间：未来 1~7 天
            start_offset = random.randint(1, 7) * 24 + random.randint(8, 20)
            start_time = now + timedelta(hours=start_offset)
            end_time = start_time + timedelta(hours=random.choice([2, 3, 4]))

            title = f"{act_type} - {random.choice(prefs) if prefs else act_type}"
            text = embedding_service.build_event_text(
                title, act_type, None, location, prefs, cons
            )
            event = Event(
                user_id=user.id,
                title=title,
                activity_type=act_type,
                start_time=start_time,
                end_time=end_time,
                location=location,
                city=None,
                city_normalized=None,
                preferences=prefs,
                constraints=cons,
                status="pending",
            )
            all_events.append((event, text))
            db.add(event)
            created_events += 1

        created_users += 1

    await db.flush()

    # 批量生成 embedding
    import asyncio
    BATCH_SIZE = 32
    for i in range(0, len(all_events), BATCH_SIZE):
        batch = all_events[i:i+BATCH_SIZE]
        texts = [t for _, t in batch]
        vecs = await embedding_service.encode_batch(texts)
        for (event, _), vec in zip(batch, vecs):
            event.embedding = vec
    await db.flush()

    logger.info(f"Generated {created_users} test users with {created_events} events (with embeddings)")

    return {
        "message": f"已生成 {created_users} 个测试用户和 {created_events} 个事件",
        "users": created_users,
        "events": created_events,
    }


@router.delete("/test/cleanup")
async def cleanup_test_data(db: AsyncSession = Depends(get_db)):
    """清理测试生成的数据（仅删除 phone 以 test_ 开头的用户及其关联数据，保留真实用户）"""
    # 找出所有测试用户
    test_users_r = await db.execute(
        select(User.id).where(User.phone.like("test_%"))
    )
    test_user_ids = [row[0] for row in test_users_r.all()]

    if not test_user_ids:
        return {"message": "没有测试数据需要清理", "deleted_users": 0}

    # 找出测试用户的 Agent ID
    test_agents_r = await db.execute(
        select(Agent.id).where(Agent.user_id.in_(test_user_ids))
    )
    test_agent_ids = [row[0] for row in test_agents_r.all()]
    all_sender_ids = test_user_ids + test_agent_ids

    # 找出测试用户的事件
    test_events_r = await db.execute(
        select(Event.id).where(Event.user_id.in_(test_user_ids))
    )
    test_event_ids = [row[0] for row in test_events_r.all()]

    # 找出涉及测试用户事件的聊天室
    test_rooms_r = await db.execute(
        select(ChatRoom.id).where(
            (ChatRoom.event_id_a.in_(test_event_ids)) | (ChatRoom.event_id_b.in_(test_event_ids))
        )
    ) if test_event_ids else None
    test_room_ids = [row[0] for row in test_rooms_r.all()] if test_rooms_r else []

    # 按依赖顺序删除
    if test_room_ids:
        await db.execute(delete(ChatMessage).where(ChatMessage.room_id.in_(test_room_ids)))
        await db.execute(delete(ChatRoomMember).where(ChatRoomMember.room_id.in_(test_room_ids)))
        await db.execute(delete(ChatRoom).where(ChatRoom.id.in_(test_room_ids)))

    if test_event_ids:
        await db.execute(delete(MatchLog).where(
            (MatchLog.event_a_id.in_(test_event_ids)) | (MatchLog.event_b_id.in_(test_event_ids))
        ))
        await db.execute(delete(Event).where(Event.id.in_(test_event_ids)))

    if all_sender_ids:
        await db.execute(delete(AgentChatMessage).where(AgentChatMessage.user_id.in_(test_user_ids)))

    if test_user_ids:
        await db.execute(delete(AgentMemory).where(AgentMemory.user_id.in_(test_user_ids)))
        # 清理测试用户在真实聊天室中的成员记录
        await db.execute(delete(ChatRoomMember).where(ChatRoomMember.user_id.in_(all_sender_ids)))

    if test_agent_ids:
        await db.execute(delete(Agent).where(Agent.id.in_(test_agent_ids)))

    await db.execute(delete(User).where(User.id.in_(test_user_ids)))
    await db.flush()

    # 重置被测试用户匹配过的真实事件
    if test_event_ids:
        await db.execute(
            Event.__table__.update()
            .where(Event.matched_event_id.in_(test_event_ids))
            .values(status="pending", matched_event_id=None, match_score=None, match_round=None)
        )
        await db.flush()

    return {"message": f"已清理 {len(test_user_ids)} 个测试用户及关联数据", "deleted_users": len(test_user_ids)}


# ── 批量匹配预览（粗排，不调 LLM） ──

@router.get("/test/match-preview-all")
async def match_preview_all(
    limit: int = 50,
    activity_type: str | None = None,
    city: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """批量预览所有 pending 事件的匹配候选（向量搜索）"""
    from app.services.matching_service import matching_service

    query = select(Event).where(Event.status == "pending").order_by(Event.created_at.desc())
    if activity_type:
        query = query.where(Event.activity_type == activity_type)
    if city:
        query = query.where(Event.city == city)
    query = query.limit(limit)

    result = await db.execute(query)
    events = result.scalars().all()

    previews = []
    for event in events:
        try:
            preview = await matching_service.preview_match(event.id, db)
            previews.append(preview)
        except Exception as e:
            logger.error(f"Preview failed for {event.id}: {e}")

    return {"total_events": len(events), "previews": previews}


# ── 统计概览 ──

@router.get("/test/stats")
async def match_stats(db: AsyncSession = Depends(get_db)):
    """返回事件和匹配的统计信息"""
    # 按活动类型统计
    type_result = await db.execute(
        select(Event.activity_type, func.count(Event.id))
        .where(Event.status == "pending")
        .group_by(Event.activity_type)
        .order_by(func.count(Event.id).desc())
    )
    by_type = [{"type": r[0], "count": r[1]} for r in type_result.fetchall()]

    # 按城市统计
    city_result = await db.execute(
        select(Event.city, func.count(Event.id))
        .where(Event.status == "pending")
        .group_by(Event.city)
        .order_by(func.count(Event.id).desc())
    )
    by_city = [{"city": r[0], "count": r[1]} for r in city_result.fetchall()]

    # 总计
    total = await db.execute(select(func.count(Event.id)).where(Event.status == "pending"))

    return {
        "total_pending": total.scalar(),
        "by_activity_type": by_type,
        "by_city": by_city,
    }


@router.delete("/users/{user_id}")
async def delete_user(user_id: UUID, db: AsyncSession = Depends(get_db)):
    """删除用户及其所有关联数据"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"error": "用户不存在"}

    user_name = user.name

    # 获取该用户的所有事件 ID
    events_r = await db.execute(select(Event.id).where(Event.user_id == user_id))
    event_ids = [row[0] for row in events_r.fetchall()]

    # 删除匹配日志（涉及该用户事件的）
    if event_ids:
        await db.execute(
            delete(MatchLog).where(
                (MatchLog.event_a_id.in_(event_ids)) | (MatchLog.event_b_id.in_(event_ids))
            )
        )

    # 删除聊天室成员和消息（涉及该用户的）
    await db.execute(delete(ChatRoomMember).where(ChatRoomMember.user_id == user_id))
    await db.execute(delete(ChatMessage).where(ChatMessage.sender_id == user_id))

    # 删除涉及该用户事件的聊天室
    if event_ids:
        await db.execute(
            delete(ChatRoom).where(
                (ChatRoom.event_id_a.in_(event_ids)) | (ChatRoom.event_id_b.in_(event_ids))
            )
        )

    # 清除其他事件中引用了该用户事件的 matched_event_id
    if event_ids:
        other_events_r = await db.execute(
            select(Event).where(Event.matched_event_id.in_(event_ids))
        )
        for evt in other_events_r.scalars().all():
            evt.matched_event_id = None
            evt.match_score = None
            evt.status = "pending"

    # 删除事件、Agent 聊天记录、记忆、Agent、用户
    await db.execute(delete(Event).where(Event.user_id == user_id))
    await db.execute(delete(AgentChatMessage).where(AgentChatMessage.user_id == user_id))
    await db.execute(delete(AgentMemory).where(AgentMemory.user_id == user_id))
    await db.execute(delete(Agent).where(Agent.user_id == user_id))
    await db.delete(user)
    await db.flush()

    logger.info(f"Deleted user {user_name} ({user_id}) and all related data")
    return {"message": f"已删除用户 {user_name} 及所有关联数据"}


# ── Prompt 管理（DB 持久化 + 内存缓存） ──

from pydantic import BaseModel as PydanticBaseModel
from app.services.prompt_builder import PromptBuilder
from app.models.prompt import PromptTemplate


class PromptUpdateBody(PydanticBaseModel):
    content: str
    description: str | None = None


@router.get("/prompts")
async def list_prompts(db: AsyncSession = Depends(get_db)):
    """列出所有可管理的 prompt 模板（默认 + DB 覆盖）"""
    # 从 DB 加载所有覆盖
    result = await db.execute(select(PromptTemplate).order_by(PromptTemplate.name))
    db_overrides = {row.name: row for row in result.scalars().all()}

    prompts = []
    for name, default_template in PromptBuilder._TEMPLATES.items():
        db_row = db_overrides.get(name)
        prompts.append({
            "name": name,
            "description": PromptBuilder._DESCRIPTIONS.get(name, ""),
            "variables": PromptBuilder._VARIABLES.get(name, []),
            "default_template": default_template,
            "override": db_row.content if db_row else None,
            "is_overridden": name in PromptBuilder._overrides,
            "updated_at": db_row.updated_at.isoformat() if db_row else None,
        })

    return prompts


@router.get("/prompts/{name}")
async def get_prompt(name: str, db: AsyncSession = Depends(get_db)):
    """获取指定 prompt 的详细信息"""
    if name not in PromptBuilder._TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' 不存在。可用: {list(PromptBuilder._TEMPLATES.keys())}")

    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.name == name)
    )
    db_row = result.scalar_one_or_none()

    return {
        "name": name,
        "description": db_row.description if db_row else None,
        "default_template": PromptBuilder._TEMPLATES[name],
        "override": db_row.content if db_row else None,
        "active_template": PromptBuilder.get_template(name),
        "is_overridden": name in PromptBuilder._overrides,
        "updated_at": db_row.updated_at.isoformat() if db_row else None,
    }


@router.put("/prompts/{name}")
async def update_prompt(
    name: str,
    body: PromptUpdateBody,
    db: AsyncSession = Depends(get_db),
):
    """覆盖指定 prompt 模板（持久化到 DB，立即生效）"""
    if name not in PromptBuilder._TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' 不存在。可用: {list(PromptBuilder._TEMPLATES.keys())}")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")

    # 尝试用空变量渲染，验证模板语法
    try:
        content.format_map({})
    except KeyError:
        pass  # 有占位符是正常的
    except (ValueError, IndexError) as e:
        raise HTTPException(status_code=400, detail=f"模板语法错误: {e}")

    # 写入 DB（upsert）
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.name == name)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.content = content
        if body.description is not None:
            existing.description = body.description
    else:
        db.add(PromptTemplate(
            name=name,
            content=content,
            description=body.description,
        ))

    await db.flush()

    # 同步到内存缓存
    PromptBuilder.override_template(name, content)

    logger.info(f"Prompt '{name}' 已覆盖并持久化到 DB")
    return {
        "message": f"Prompt '{name}' 已更新",
        "name": name,
        "is_overridden": True,
    }


@router.delete("/prompts/{name}")
async def delete_prompt(name: str, db: AsyncSession = Depends(get_db)):
    """删除 prompt 覆盖，恢复为默认模板"""
    if name not in PromptBuilder._TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' 不存在")

    # 从 DB 删除
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.name == name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()

    # 从内存缓存移除
    PromptBuilder.reset_template(name)

    logger.info(f"Prompt '{name}' 已重置为默认模板")
    return {
        "message": f"Prompt '{name}' 已重置为默认值",
        "name": name,
        "is_overridden": False,
    }
