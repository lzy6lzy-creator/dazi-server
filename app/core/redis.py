from __future__ import annotations

"""
Redis 连接管理 + Agent 对话历史缓存
"""
import asyncio
import json
import logging
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
