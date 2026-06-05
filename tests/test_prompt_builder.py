from __future__ import annotations

import unittest

from app.services.prompt_builder import PromptBuilder


class PromptBuilderTests(unittest.TestCase):
    def test_main_conversation_uses_single_orchestrator_prompt(self):
        prompt_names = {item["name"] for item in PromptBuilder.list_prompts()}

        self.assertIn("conversation_orchestrator", prompt_names)
        self.assertNotIn("agent_chat", prompt_names)
        self.assertNotIn("clarification_questions", prompt_names)
        self.assertNotIn("event_extraction", prompt_names)

    def test_conversation_orchestrator_prompt_includes_state_and_json_actions(self):
        prompt = PromptBuilder.build_conversation_orchestrator_prompt(
            user_name="小明",
            user_city="上海",
            user_interests=["火锅"],
            user_bio="",
            birth_date=None,
            memories=[("constraint", "不吃辣")],
            conversation_state="当前已有待确认活动草稿",
        )

        self.assertIn("chat|clarify|draft|cancel", prompt)
        self.assertIn("当前已有待确认活动草稿", prompt)
        self.assertIn("不吃辣", prompt)
        self.assertNotIn("[EVENT_DRAFT]", prompt)
        self.assertNotIn("[EVENT_READY]", prompt)

    def test_conversation_orchestrator_prompt_matches_kimi_gate_rules(self):
        prompt = PromptBuilder.build_conversation_orchestrator_prompt(
            user_name="小明",
            user_city="上海",
            user_interests=["网球"],
            user_bio="",
            birth_date="1998-06-05",
            memories=[],
            conversation_state="无待处理状态",
        )

        self.assertIn("action 必须是 clarify，而不是 draft", prompt)
        self.assertIn("本轮 clarify 只能问 1 个问题：id=city", prompt)
        self.assertIn("上海更偏向哪片区域？", prompt)
        self.assertIn("首轮澄清必须问 time、skill、cost", prompt)
        self.assertIn("新手也行", prompt)
        self.assertIn("场地费 AA", prompt)


if __name__ == "__main__":
    unittest.main()
