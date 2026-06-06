from __future__ import annotations

import unittest

from app.api.agent_chat import _events_from_conversation_decision
from app.api.agent_chat import _events_from_draft_payload
from app.api.agent_chat import _events_from_agent_response
from app.api.agent_chat import _merge_stream_draft_with_structured_answers
from app.api.schemas import AgentChatResponse


class AgentChatStreamTests(unittest.TestCase):
    def test_events_from_clarify_decision_emit_clarify_and_done(self):
        events = list(_events_from_conversation_decision(
            decision={
                "action": "clarify",
                "reply": "我先帮你确认几个点。",
                "questions": [{"id": "time", "title": "时间", "options": [{"id": "t", "label": "今晚"}]}],
                "draft": {"activity_type": "羽毛球"},
            },
            session_id="session-1",
        ))

        self.assertEqual(events[0][0], "clarify")
        self.assertEqual(events[0][1]["session_id"], "session-1")
        self.assertEqual(events[0][1]["questions"][0]["id"], "time")
        self.assertEqual(events[-1], ("done", {}))

    def test_events_from_draft_payload_emit_draft_ready(self):
        events = list(_events_from_draft_payload(
            payload={
                "reply": "草稿整理好了。",
                "draft": {"activity_type": "咖啡"},
            }
        ))

        self.assertEqual(events[0], ("draft_ready", {"event_draft_pending": True}))
        self.assertEqual(events[-1], ("done", {}))

    def test_events_from_draft_payload_emit_reply_fallback_when_no_delta_streamed(self):
        events = list(_events_from_draft_payload(
            payload={
                "reply": "草稿整理好了。",
                "draft": {"activity_type": "咖啡"},
            },
            include_reply=True,
        ))

        self.assertEqual(events[0], ("draft_delta", {"text": "草稿整理好了。"}))
        self.assertEqual(events[1], ("draft_ready", {"event_draft_pending": True}))

    def test_events_from_agent_response_emit_reply_fallback_when_no_delta_streamed(self):
        events = list(_events_from_agent_response(
            AgentChatResponse(reply="能啊，测试成功。"),
            include_reply=True,
        ))

        self.assertEqual(events[0], ("reply_delta", {"text": "能啊，测试成功。"}))
        self.assertEqual(events[-1], ("done", {}))

    def test_events_from_agent_response_skip_reply_fallback_after_delta_streamed(self):
        events = list(_events_from_agent_response(
            AgentChatResponse(reply="能啊，测试成功。"),
            include_reply=False,
        ))

        self.assertNotIn(("reply_delta", {"text": "能啊，测试成功。"}), events)
        self.assertEqual(events[-1], ("done", {}))

    def test_stream_draft_merge_preserves_structured_age_and_gender_answers(self):
        merged = _merge_stream_draft_with_structured_answers(
            {
                "title": "今晚火锅",
                "activity_type": "火锅",
                "preferences": ["年龄偏好 23-33 岁", "搭子性别偏好：女生优先"],
                "constraints": [],
                "age_filter_min": 23,
                "age_filter_max": 33,
                "age_filter_mode": "preference",
                "clarification_answers": [{"question_id": "age"}],
            },
            {
                "title": "今晚徐汇火锅",
                "activity_type": "火锅",
                "preferences": ["不吃太辣"],
                "constraints": [],
            },
        )

        self.assertEqual(merged["title"], "今晚徐汇火锅")
        self.assertEqual(merged["age_filter_min"], 23)
        self.assertEqual(merged["age_filter_max"], 33)
        self.assertEqual(merged["age_filter_mode"], "preference")
        self.assertEqual(
            merged["preferences"],
            ["年龄偏好 23-33 岁", "搭子性别偏好：女生优先", "不吃太辣"],
        )
        self.assertEqual(merged["clarification_answers"], [{"question_id": "age"}])

if __name__ == "__main__":
    unittest.main()
