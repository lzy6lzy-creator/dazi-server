"""
User & Agent API - 用户信息、Agent 配置
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.user import User, Agent, AgentMemory
from app.services.embedding_service import embedding_service
from app.api.schemas import (
    UserResponse, UserUpdate,
    AgentResponse, AgentUpdate,
    MemoryResponse, MemoryUpdate,
    PublicUserProfileResponse,
)

router = APIRouter(prefix="/api/v1", tags=["users"])


# ── User ──

@router.get("/users/me", response_model=UserResponse)
async def get_me(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.put("/users/me", response_model=UserResponse)
async def update_me(
    data: UserUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    # 当兴趣相关字段变化时，重新生成 embedding
    embedding_fields = {"interests", "custom_interests", "occupation"}
    if embedding_fields & update_data.keys():
        user.embedding = await _generate_user_embedding(user)

    await db.flush()
    return user


@router.get("/users/{profile_user_id}/profile", response_model=PublicUserProfileResponse)
async def get_public_user_profile(
    profile_user_id: UUID,
    _viewer_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == profile_user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


# ── Agent ──

@router.get("/agents/me", response_model=AgentResponse)
async def get_my_agent(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Agent).where(Agent.user_id == user_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return agent


@router.put("/agents/me", response_model=AgentResponse)
async def update_my_agent(
    data: AgentUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Agent).where(Agent.user_id == user_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)

    await db.flush()
    return agent


# ── Agent Memories ──

@router.get("/agents/me/memories", response_model=list[MemoryResponse])
async def get_my_memories(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentMemory)
        .where(
            AgentMemory.user_id == user_id,
            AgentMemory.is_active == True,
            AgentMemory.status != "inactive",
        )
        .order_by(AgentMemory.confidence.desc())
    )
    return result.scalars().all()


@router.patch("/agents/me/memories/{memory_id}", response_model=MemoryResponse)
async def update_my_memory(
    memory_id: UUID,
    data: MemoryUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")

    if data.content is not None:
        memory.content = data.content.strip()
    if data.status is not None:
        memory.status = data.status
        memory.is_active = data.status == "active"
    if data.is_active is not None:
        memory.is_active = data.is_active
        memory.status = "active" if data.is_active else "inactive"
    memory.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return memory


@router.delete("/agents/me/memories/{memory_id}")
async def delete_my_memory(
    memory_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")

    memory.is_active = False
    memory.status = "inactive"
    memory.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return {"ok": True}


# ── Helpers ──

async def _generate_user_embedding(user: User) -> list[float] | None:
    """基于用户兴趣信息生成 embedding"""
    parts = []
    if user.interests:
        parts.append(f"爱好: {', '.join(user.interests)}")
    if user.custom_interests:
        parts.append(user.custom_interests)
    if user.occupation:
        parts.append(f"职业: {user.occupation}")
    if not parts:
        return None
    text = ". ".join(parts)
    return await embedding_service.encode(text)
