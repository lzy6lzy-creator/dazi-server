"""
Event API - 活动 CRUD + 匹配触发
"""
import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.embedding_service import embedding_service

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.event import Event
from app.api.schemas import EventCreate, EventUpdate, EventResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("", response_model=EventResponse)
async def create_event(
    data: EventCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    event = Event(
        user_id=user_id,
        title=data.title,
        activity_type=data.activity_type,
        city=data.city,
        city_normalized=await embedding_service.align_city(data.city),
        start_time=data.start_time,
        end_time=data.end_time,
        location=data.location,
        preferences=data.preferences or [],
        constraints=data.constraints or [],
        status="pending",
    )
    db.add(event)
    await db.flush()

    # 生成 embedding
    text = embedding_service.build_event_text(
        event.title, event.activity_type, event.city,
        event.location, event.preferences, event.constraints
    )
    event.embedding = await embedding_service.encode(text)

    return event


@router.get("", response_model=list[EventResponse])
async def list_events(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event)
        .where(Event.user_id == user_id)
        .order_by(Event.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.user_id == user_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="活动不存在")
    return event


@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: UUID,
    data: EventUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.user_id == user_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="活动不存在或无权修改")
    if event.status != "pending":
        raise HTTPException(status_code=400, detail=f"活动状态为 {event.status}，只有待匹配的活动可以编辑")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(event, field, value)

    if "city" in update_data:
        event.city_normalized = await embedding_service.align_city(event.city)

    # 重新生成 embedding
    text = embedding_service.build_event_text(
        event.title, event.activity_type, event.city,
        event.location, event.preferences, event.constraints
    )
    event.embedding = await embedding_service.encode(text)

    await db.flush()
    return event


@router.delete("/{event_id}")
async def cancel_event(
    event_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.user_id == user_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="活动不存在或无权操作")
    if event.status not in ("pending", "matching"):
        raise HTTPException(status_code=400, detail=f"活动状态为 {event.status}，无法取消")

    event.status = "cancelled"
    await db.flush()
    return {"message": "活动已取消"}


@router.post("/{event_id}/match")
async def trigger_matching(
    event_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """手动触发匹配（也可由系统定时触发）"""
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.user_id == user_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="活动不存在或无权操作")
    if event.status != "pending":
        raise HTTPException(status_code=400, detail=f"活动状态为 {event.status}，无法匹配")

    background_tasks.add_task(_run_matching, event_id)
    return {"message": "匹配已触发", "event_id": str(event_id)}


async def _run_matching(event_id: UUID):
    """后台匹配任务"""
    from app.core.database import async_session
    from app.services.matching_service import matching_service

    try:
        async with async_session() as db:
            result = await matching_service.match_event(event_id, db)
            await db.commit()
            if result:
                logger.info(f"Match found for event {event_id}: score={result['score']}")
            else:
                logger.info(f"No match found for event {event_id}")
    except Exception as e:
        logger.error(f"Matching task failed for {event_id}: {e}")
