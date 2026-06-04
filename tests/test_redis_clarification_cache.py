from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.core.redis import ChatHistoryCache


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, *keys: str):
        for key in keys:
            self.values.pop(key, None)


class ClarificationCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_clarification_session_tracks_and_clears_active_session(self):
        fake = FakeRedis()
        payload = {
            "reply": "我先帮你确认几个点。",
            "questions": [{"id": "location", "title": "地点？", "options": []}],
        }

        with patch("app.core.redis.get_redis", new=AsyncMock(return_value=fake)):
            await ChatHistoryCache.set_clarification_session("user-1", "session-1", payload)

            latest = await ChatHistoryCache.get_latest_clarification_session("user-1")
            self.assertEqual(latest, {
                "session_id": "session-1",
                "reply": "我先帮你确认几个点。",
                "questions": [{"id": "location", "title": "地点？", "options": []}],
            })

            await ChatHistoryCache.clear_clarification_session("user-1", "session-1")

            self.assertIsNone(await ChatHistoryCache.get_latest_clarification_session("user-1"))

    async def test_clearing_old_session_does_not_clear_newer_latest_session(self):
        fake = FakeRedis()

        with patch("app.core.redis.get_redis", new=AsyncMock(return_value=fake)):
            await ChatHistoryCache.set_clarification_session("user-1", "old-session", {"reply": "old"})
            await ChatHistoryCache.set_clarification_session("user-1", "new-session", {"reply": "new"})

            await ChatHistoryCache.clear_clarification_session("user-1", "old-session")

            latest = await ChatHistoryCache.get_latest_clarification_session("user-1")
            self.assertEqual(latest, {"session_id": "new-session", "reply": "new"})


if __name__ == "__main__":
    unittest.main()
