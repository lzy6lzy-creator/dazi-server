from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.api.agent_chat import _can_publish_existing_draft_without_llm
from app.api.agent_chat import _build_memory_source_after_publish
from app.api.agent_chat import _editing_event_intro_reply
from app.api.agent_chat import _parse_draft_datetime
from app.api.agent_chat import _start_new_agent_chat_session_after_event_ready
from app.api.agent_chat import SESSION_RESET_PREFIX
from app.api.agent_chat import SESSION_RESET_ROLE


class AgentChatFlowHelperTests(unittest.IsolatedAsyncioTestCase):
    def test_can_publish_existing_draft_on_direct_confirmation(self):
        draft = {"title": "今晚火锅", "activity_type": "火锅"}

        self.assertTrue(_can_publish_existing_draft_without_llm(draft, "确认"))
        self.assertTrue(_can_publish_existing_draft_without_llm(draft, "确认发布"))

    def test_does_not_publish_without_draft_or_confirmation(self):
        draft = {"title": "今晚火锅", "activity_type": "火锅"}

        self.assertFalse(_can_publish_existing_draft_without_llm({}, "确认"))
        self.assertFalse(_can_publish_existing_draft_without_llm(draft, "我人在上海，重新问"))

    def test_memory_source_after_publish_uses_final_event_context(self):
        text = _build_memory_source_after_publish(
            user_message="确认",
            draft={
                "title": "今晚火锅",
                "activity_type": "火锅",
                "city": "上海",
                "location": "徐汇",
                "preferences": ["实惠", "正常吃"],
                "constraints": ["不吃辣"],
            },
        )

        self.assertIn("用户发布了一次活动", text)
        self.assertIn("今晚火锅", text)
        self.assertIn("地点：徐汇", text)
        self.assertIn("实惠、正常吃", text)
        self.assertIn("不吃辣", text)

    def test_editing_event_intro_uses_button_flow_without_legacy_markers(self):
        reply = _editing_event_intro_reply(
            title="今晚咖啡",
            activity_type="咖啡",
            start_time_text="未设",
            place_text="上海 / 徐汇",
            preferences=["安静", "时间灵活"],
            constraints=["不抽烟"],
        )

        self.assertIn("今晚咖啡", reply)
        self.assertIn("上海 / 徐汇", reply)
        self.assertIn("直接告诉我你想改哪里", reply)
        self.assertNotIn("[EVENT_DRAFT]", reply)
        self.assertNotIn("[EVENT_READY]", reply)

    def test_parse_draft_datetime_treats_naive_time_as_beijing_time(self):
        parsed = _parse_draft_datetime("2026-06-06T14:00:00")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset().total_seconds(), 8 * 3600)
        self.assertEqual(parsed.isoformat(), "2026-06-06T14:00:00+08:00")

    def test_parse_draft_datetime_preserves_explicit_timezone(self):
        parsed = _parse_draft_datetime("2026-06-06T14:00:00+00:00")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    async def test_event_ready_starts_new_agent_chat_session(self):
        user_id = uuid4()
        event_id = uuid4()
        added = []

        class FakeDB:
            def add(self, item):
                added.append(item)

            async def flush(self):
                return None

        with patch(
            "app.api.agent_chat.ChatHistoryCache.start_new_agent_chat_session",
            new=AsyncMock(),
        ) as start_session:
            await _start_new_agent_chat_session_after_event_ready(
                user_id=user_id,
                uid_str=str(user_id),
                event_id=event_id,
                db=FakeDB(),
            )

        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].role, SESSION_RESET_ROLE)
        self.assertTrue(added[0].content.startswith(f"{SESSION_RESET_PREFIX}:"))
        start_session.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
