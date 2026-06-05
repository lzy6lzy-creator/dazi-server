from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.api.agent_chat import _apply_conversation_decision
from app.api.agent_chat import _can_publish_existing_draft_without_llm
from app.api.agent_chat import _build_memory_source_after_publish
from app.api.agent_chat import _editing_event_intro_reply
from app.api.agent_chat import _parse_draft_datetime
from app.api.agent_chat import _publish_existing_draft_without_llm
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

    async def test_apply_conversation_decision_uses_llm_questions_without_rule_injection(self):
        user_id = uuid4()
        added = []

        class FakeDB:
            def add(self, item):
                added.append(item)

            async def flush(self):
                return None

        decision = {
            "action": "clarify",
            "reply": "我先把需要确认的点整理成卡片。",
            "draft": {
                "title": "周日下午看电影",
                "activity_type": "看电影",
                "preferences": [],
                "constraints": [],
            },
            "questions": [
                {
                    "id": "skill",
                    "type": "single_choice",
                    "title": "观影偏好？",
                    "options": [{"id": "quiet", "label": "安静看"}],
                }
            ],
        }

        with patch(
            "app.api.agent_chat.ChatHistoryCache.set_clarification_session",
            new=AsyncMock(),
        ) as set_session, patch(
            "app.api.agent_chat.ChatHistoryCache.append_message",
            new=AsyncMock(),
        ):
            response = await _apply_conversation_decision(
                user=SimpleNamespace(id=user_id),
                uid_str=str(user_id),
                message="周日下午看电影",
                decision=decision,
                pending_clarification=None,
                current_location="上海市徐汇区",
                db=FakeDB(),
            )

        self.assertTrue(response.clarification_pending)
        self.assertEqual([question.id for question in response.clarification_questions], ["skill"])
        stored_session = set_session.await_args.args[2]
        self.assertEqual([question["id"] for question in stored_session["questions"]], ["skill"])
        self.assertNotIn("location", stored_session["draft"])
        self.assertEqual(len(added), 2)

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

    async def test_publish_commits_before_scheduling_background_work(self):
        user_id = uuid4()
        order = []

        class FakeDB:
            def __init__(self):
                self.added = []

            def add(self, item):
                self.added.append(item)

            async def flush(self):
                for item in self.added:
                    if getattr(item, "id", None) is None:
                        item.id = uuid4()
                    if getattr(item, "created_at", None) is None:
                        item.created_at = datetime.now(timezone.utc)

            async def commit(self):
                order.append("commit")

            async def rollback(self):
                order.append("rollback")

        class FakeBackgroundTasks:
            def add_task(self, *_args, **_kwargs):
                order.append("memory")

        draft = {
            "title": "周六火锅局",
            "activity_type": "火锅",
            "location": "杨浦",
            "preferences": ["重辣"],
            "constraints": [],
        }

        with patch(
            "app.api.agent_chat.ChatHistoryCache.get_event_draft",
            new=AsyncMock(return_value=draft),
        ), patch(
            "app.api.agent_chat.ChatHistoryCache.append_message",
            new=AsyncMock(),
        ), patch(
            "app.api.agent_chat.ChatHistoryCache.start_new_agent_chat_session",
            new=AsyncMock(),
        ), patch(
            "app.api.agent_chat.ChatHistoryCache.clear_event_draft",
            new=AsyncMock(),
        ) as clear_draft, patch(
            "app.api.agent_chat.embedding_service.encode",
            new=AsyncMock(return_value=[0.0] * 768),
        ), patch(
            "app.api.agent_chat.schedule_event_matching",
            new=lambda *_args, **_kwargs: order.append("matching"),
        ):
            response = await _publish_existing_draft_without_llm(
                user=SimpleNamespace(id=user_id),
                uid_str=str(user_id),
                message="确认",
                editing_event_id=None,
                background_tasks=FakeBackgroundTasks(),
                db=FakeDB(),
            )

        self.assertTrue(response.event_ready)
        self.assertEqual(order, ["commit", "matching", "memory"])
        clear_draft.assert_awaited_once_with(str(user_id))

    async def test_publish_keeps_draft_when_commit_fails(self):
        user_id = uuid4()

        class FakeDB:
            def __init__(self):
                self.added = []
                self.rolled_back = False

            def add(self, item):
                self.added.append(item)

            async def flush(self):
                for item in self.added:
                    if getattr(item, "id", None) is None:
                        item.id = uuid4()
                    if getattr(item, "created_at", None) is None:
                        item.created_at = datetime.now(timezone.utc)

            async def commit(self):
                raise RuntimeError("commit failed")

            async def rollback(self):
                self.rolled_back = True

        class FakeBackgroundTasks:
            def add_task(self, *_args, **_kwargs):
                raise AssertionError("background work should not be scheduled")

        draft = {
            "title": "周六火锅局",
            "activity_type": "火锅",
            "location": "杨浦",
            "preferences": [],
            "constraints": [],
        }
        db = FakeDB()

        with patch(
            "app.api.agent_chat.ChatHistoryCache.get_event_draft",
            new=AsyncMock(return_value=draft),
        ), patch(
            "app.api.agent_chat.ChatHistoryCache.append_message",
            new=AsyncMock(),
        ), patch(
            "app.api.agent_chat.ChatHistoryCache.start_new_agent_chat_session",
            new=AsyncMock(),
        ), patch(
            "app.api.agent_chat.ChatHistoryCache.clear_event_draft",
            new=AsyncMock(),
        ) as clear_draft, patch(
            "app.api.agent_chat.embedding_service.encode",
            new=AsyncMock(return_value=[0.0] * 768),
        ), patch(
            "app.api.agent_chat.schedule_event_matching",
            new=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("matching should not be scheduled")
            ),
        ), patch(
            "app.api.agent_chat.logger.exception",
        ):
            response = await _publish_existing_draft_without_llm(
                user=SimpleNamespace(id=user_id),
                uid_str=str(user_id),
                message="确认",
                editing_event_id=None,
                background_tasks=FakeBackgroundTasks(),
                db=db,
            )

        self.assertFalse(response.event_ready)
        self.assertIn("出了点问题", response.reply)
        self.assertTrue(db.rolled_back)
        clear_draft.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
