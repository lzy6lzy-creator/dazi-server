from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.site_feedback import SiteFeedback


router = APIRouter(prefix="/api/v1", tags=["feedback"])

FEEDBACK_CATEGORIES = {"体验问题", "功能建议", "报名问题", "其他"}


class FeedbackCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=40)
    content: str = Field(..., min_length=2, max_length=1000)
    contact: str | None = Field(default=None, max_length=160)
    source: str = Field(default="homepage", max_length=40)

    @field_validator("category", "content", "contact", "source", mode="before")
    @classmethod
    def strip_text(cls, value):
        if value is None:
            return None
        return str(value).strip()

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in FEEDBACK_CATEGORIES:
            raise ValueError("请选择有效的反馈类型")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        text = value.strip()
        if len(text) < 2:
            raise ValueError("反馈内容至少需要 2 个字")
        return text


def client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return None


@router.post("/feedback", status_code=201)
async def create_feedback(
    payload: FeedbackCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a public website feedback record."""
    now = datetime.now(timezone.utc)
    feedback = SiteFeedback(
        category=payload.category,
        content=payload.content,
        contact=payload.contact or None,
        source=payload.source or "homepage",
        status="new",
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        created_at=now,
        updated_at=now,
    )
    db.add(feedback)

    try:
        await db.flush()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="反馈保存失败") from exc

    return {
        "success": True,
        "id": str(feedback.id),
        "message": "反馈已收到，谢谢你帮我们改进。",
    }
