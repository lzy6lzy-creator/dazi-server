"""
Event API - 活动 CRUD + 匹配触发
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.embedding_service import embedding_service

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.event import Event
from app.api.schemas import EventCreate, EventUpdate, EventResponse
from app.services.matching_tasks import schedule_event_matching

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def _single_location(location: str | None, legacy_city: str | None = None) -> str | None:
    location_value = location.strip() if isinstance(location, str) and location.strip() else None
    city_value = legacy_city.strip() if isinstance(legacy_city, str) and legacy_city.strip() else None
    return location_value or city_value


@router.post("", response_model=EventResponse)
async def create_event(
    data: EventCreate,
    background_tasks: BackgroundTasks = None,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    location_value = _single_location(data.location, data.city)
    event = Event(
        user_id=user_id,
        title=data.title,
        activity_type=data.activity_type,
        city=None,
        city_normalized=None,
        start_time=data.start_time,
        end_time=data.end_time,
        location=location_value,
        preferences=data.preferences or [],
        constraints=data.constraints or [],
        clarification_answers=data.clarification_answers,
        age_filter_min=data.age_filter_min,
        age_filter_max=data.age_filter_max,
        age_filter_mode=data.age_filter_mode,
        status="pending",
    )
    db.add(event)
    await db.flush()

    # 生成 embedding
    text = embedding_service.build_event_text(
        event.title, event.activity_type, None,
        event.location, event.preferences, event.constraints
    )
    event.embedding = await embedding_service.encode(text)

    schedule_event_matching(background_tasks, event.id)
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
    if "city" in update_data:
        if "location" not in update_data:
            update_data["location"] = update_data.get("city")
        update_data.pop("city", None)
    for field, value in update_data.items():
        setattr(event, field, value)

    event.location = _single_location(event.location)
    event.city = None
    event.city_normalized = None

    # 重新生成 embedding
    text = embedding_service.build_event_text(
        event.title, event.activity_type, None,
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

    schedule_event_matching(background_tasks, event_id)
    return {"message": "匹配已触发", "event_id": str(event_id)}
