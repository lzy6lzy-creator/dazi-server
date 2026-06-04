from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.beta_signup import BetaSignup


router = APIRouter(prefix="/api/v1", tags=["beta"])

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


class BetaSignupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., min_length=3, max_length=160)
    contact: str = Field(..., min_length=11, max_length=11)
    city: str | None = Field(default=None, max_length=80)
    device: str | None = Field(default=None, max_length=120)
    activity_interests: list[str] = Field(default_factory=list, max_length=12)
    note: str | None = Field(default=None, max_length=500)
    source: str = Field(default="homepage", max_length=40)
    consent: bool

    @field_validator("name", "email", "contact", "city", "device", "note", "source", mode="before")
    @classmethod
    def strip_text(cls, value):
        if value is None:
            return None
        return str(value).strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not EMAIL_PATTERN.match(email):
            raise ValueError("请填写有效邮箱")
        return email

    @field_validator("contact")
    @classmethod
    def validate_contact_phone(cls, value: str) -> str:
        phone = re.sub(r"[\s-]+", "", value.strip())
        if not PHONE_PATTERN.match(phone):
            raise ValueError("请填写 11 位中国大陆手机号")
        return phone

    @field_validator("activity_interests", mode="before")
    @classmethod
    def normalize_activity_interests(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = re.split(r"[,\s，、]+", value)
        else:
            raw_items = value
        items = []
        for item in raw_items:
            text = str(item).strip()
            if text and text not in items:
                items.append(text[:30])
        return items[:12]

    @field_validator("consent")
    @classmethod
    def require_consent(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("需要同意用于内测邀请和联系")
        return value


def client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return None


@router.post("/beta-signups", status_code=201)
async def create_beta_signup(
    payload: BetaSignupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create or update a homepage TestFlight beta signup."""
    result = await db.execute(
        select(BetaSignup)
        .where(func.lower(BetaSignup.email) == payload.email.lower())
        .order_by(BetaSignup.created_at.desc())
        .limit(1)
    )
    signup = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    was_existing = signup is not None

    if signup is None:
        signup = BetaSignup(
            name=payload.name,
            email=payload.email.lower(),
            source=payload.source or "homepage",
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        db.add(signup)

    signup.name = payload.name
    signup.email = payload.email.lower()
    signup.contact = payload.contact or None
    signup.city = payload.city or None
    signup.device = payload.device or None
    signup.activity_interests = payload.activity_interests
    signup.note = payload.note or None
    signup.source = payload.source or "homepage"
    signup.status = "updated" if was_existing else "new"
    signup.ip_address = client_ip(request)
    signup.user_agent = request.headers.get("user-agent")
    signup.updated_at = now

    try:
        await db.flush()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="报名保存失败") from exc

    return {
        "success": True,
        "id": str(signup.id),
        "status": signup.status,
        "message": "报名已收到，我们会用你填写的 Apple ID 邮箱发送 TestFlight 邀请。",
    }
