from __future__ import annotations

import unittest

from app.api.agent_chat import _can_publish_existing_draft_without_llm
from app.api.agent_chat import _build_memory_source_after_publish
from app.api.agent_chat import _editing_event_intro_reply


class AgentChatFlowHelperTests(unittest.TestCase):
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
        self.assertIn("上海 / 徐汇", text)
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


if __name__ == "__main__":
    unittest.main()
