from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PushDeviceTokenRequest, PushDeviceTokenResponse
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.user import PushDeviceToken

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.post("/device-token", response_model=PushDeviceTokenResponse)
async def register_device_token(
    data: PushDeviceTokenRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(select(PushDeviceToken).where(PushDeviceToken.token == data.token))
    row = result.scalar_one_or_none()

    if row:
        row.user_id = user_id
        row.platform = data.platform
        row.environment = data.environment
        row.is_active = True
        row.last_seen_at = now
        row.updated_at = now
    else:
        db.add(PushDeviceToken(
            user_id=user_id,
            token=data.token,
            platform=data.platform,
            environment=data.environment,
            is_active=True,
            last_seen_at=now,
        ))

    await db.flush()
    return PushDeviceTokenResponse(registered=True)


@router.delete("/device-token", response_model=PushDeviceTokenResponse)
async def unregister_device_token(
    data: PushDeviceTokenRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PushDeviceToken).where(
            PushDeviceToken.token == data.token,
            PushDeviceToken.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.is_active = False
        row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return PushDeviceTokenResponse(registered=False)
