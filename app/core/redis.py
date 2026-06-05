from __future__ import annotations

"""
Redis 连接管理 + Agent 对话历史缓存
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

# 全局 Redis 连接池
_redis: Optional[aioredis.Redis] = None
_redis_lock = asyncio.Lock()


async def get_redis() -> aioredis.Redis:
    """获取 Redis 连接（带连接池复用）"""
    global _redis
    if _redis is None:
        async with _redis_lock:
            if _redis is None:
                _redis = aioredis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    max_connections=20,
                )
    return _redis


async def close_redis():
    """关闭 Redis 连接"""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


class ChatHistoryCache:
    """
    Agent 对话历史 Redis 缓存

    key 格式: agent_chat:{user_id}
    存储: 最近 N 轮对话的 JSON 列表
    TTL: 24 小时（超过则从 DB 重新加载）
    """

    PREFIX = "agent_chat"
    SESSION_START_PREFIX = "agent_chat_session_start"
    MAX_ROUNDS = 20  # 保留最近 20 轮（40 条消息）
    TTL_SECONDS = 86400  # 24 小时

    @staticmethod
    def _key(user_id: str) -> str:
        return f"{ChatHistoryCache.PREFIX}:{user_id}"

    @classmethod
    async def get_history(cls, user_id: str) -> list[dict]:
        """获取用户的对话历史"""
        r = await get_redis()
        key = cls._key(user_id)
        data = await r.get(key)
        if data:
            return json.loads(data)
        return []

    @classmethod
    async def append_message(cls, user_id: str, role: str, content: str):
        """追加一条消息到对话历史"""
        r = await get_redis()
        key = cls._key(user_id)

        history = await cls.get_history(user_id)
        history.append({"role": role, "content": content})

        # 只保留最近 MAX_ROUNDS * 2 条消息
        max_messages = cls.MAX_ROUNDS * 2
        if len(history) > max_messages:
            history = history[-max_messages:]

        await r.set(key, json.dumps(history, ensure_ascii=False), ex=cls.TTL_SECONDS)

    @classmethod
    async def clear_history(cls, user_id: str):
        """清空对话历史"""
        r = await get_redis()
        await r.delete(cls._key(user_id))

    @classmethod
    async def start_new_agent_chat_session(cls, user_id: str, started_at: datetime | None = None):
        """记录新的主对话 session 起点，并清空 Redis 中的旧历史。"""
        r = await get_redis()
        timestamp = started_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        await r.delete(cls._key(user_id))
        await r.set(f"{cls.SESSION_START_PREFIX}:{user_id}", timestamp.isoformat())

    @classmethod
    async def get_agent_chat_session_start(cls, user_id: str) -> datetime | None:
        """获取主对话 session 起点。"""
        r = await get_redis()
        value = await r.get(f"{cls.SESSION_START_PREFIX}:{user_id}")
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @classmethod
    async def set_history(cls, user_id: str, history: list[dict]):
        """覆盖设置对话历史（从 DB 恢复时使用）"""
        r = await get_redis()
        key = cls._key(user_id)
        max_messages = cls.MAX_ROUNDS * 2
        if len(history) > max_messages:
            history = history[-max_messages:]
        await r.set(key, json.dumps(history, ensure_ascii=False), ex=cls.TTL_SECONDS)

    # ── Event Draft 缓存 ──

    DRAFT_PREFIX = "event_draft"
    DRAFT_TTL = 3600  # 1 小时

    @classmethod
    async def set_event_draft(cls, user_id: str, draft: dict):
        """存储事件草稿"""
        r = await get_redis()
        key = f"{cls.DRAFT_PREFIX}:{user_id}"
        await r.set(key, json.dumps(draft, ensure_ascii=False), ex=cls.DRAFT_TTL)

    @classmethod
    async def get_event_draft(cls, user_id: str) -> dict | None:
        """获取事件草稿"""
        r = await get_redis()
        key = f"{cls.DRAFT_PREFIX}:{user_id}"
        data = await r.get(key)
        if data:
            return json.loads(data)
        return None

    @classmethod
    async def clear_event_draft(cls, user_id: str):
        """清除事件草稿"""
        r = await get_redis()
        await r.delete(f"{cls.DRAFT_PREFIX}:{user_id}")

    # ── Event Editing 状态 ──

    EDITING_PREFIX = "editing_event"
    EDITING_TTL = 3600  # 1 小时

    @classmethod
    async def set_editing_event(cls, user_id: str, event_id: str):
        """标记用户正在编辑某个事件"""
        r = await get_redis()
        key = f"{cls.EDITING_PREFIX}:{user_id}"
        await r.set(key, event_id, ex=cls.EDITING_TTL)

    @classmethod
    async def get_editing_event(cls, user_id: str) -> str | None:
        """获取用户正在编辑的事件 ID"""
        r = await get_redis()
        key = f"{cls.EDITING_PREFIX}:{user_id}"
        return await r.get(key)

    @classmethod
    async def clear_editing_event(cls, user_id: str):
        """清除编辑状态"""
        r = await get_redis()
        await r.delete(f"{cls.EDITING_PREFIX}:{user_id}")

    # ── Clarification session 缓存 ──

    CLARIFICATION_PREFIX = "clarification"
    CLARIFICATION_LATEST_PREFIX = "clarification_latest"
    CLARIFICATION_TTL = 3600

    @classmethod
    async def set_clarification_session(cls, user_id: str, session_id: str, payload: dict):
        """存储结构化澄清会话。"""
        r = await get_redis()
        key = f"{cls.CLARIFICATION_PREFIX}:{user_id}:{session_id}"
        await r.set(key, json.dumps(payload, ensure_ascii=False), ex=cls.CLARIFICATION_TTL)
        await r.set(
            f"{cls.CLARIFICATION_LATEST_PREFIX}:{user_id}",
            session_id,
            ex=cls.CLARIFICATION_TTL,
        )

    @classmethod
    async def get_clarification_session(cls, user_id: str, session_id: str) -> dict | None:
        """获取结构化澄清会话。"""
        r = await get_redis()
        key = f"{cls.CLARIFICATION_PREFIX}:{user_id}:{session_id}"
        data = await r.get(key)
        if data:
            return json.loads(data)
        return None

    @classmethod
    async def get_latest_clarification_session(cls, user_id: str) -> dict | None:
        """获取用户最近一条仍有效的结构化澄清会话。"""
        r = await get_redis()
        latest_key = f"{cls.CLARIFICATION_LATEST_PREFIX}:{user_id}"
        session_id = await r.get(latest_key)
        if not session_id:
            return None

        payload = await cls.get_clarification_session(user_id, session_id)
        if payload is None:
            await r.delete(latest_key)
            return None

        return {"session_id": session_id, **payload}

    @classmethod
    async def clear_clarification_session(cls, user_id: str, session_id: str):
        """清除结构化澄清会话。"""
        r = await get_redis()
        latest_key = f"{cls.CLARIFICATION_LATEST_PREFIX}:{user_id}"
        latest_session_id = await r.get(latest_key)
        keys = [f"{cls.CLARIFICATION_PREFIX}:{user_id}:{session_id}"]
        if latest_session_id == session_id:
            keys.append(latest_key)
        await r.delete(*keys)
