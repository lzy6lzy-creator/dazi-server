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

    def test_room_agent_prompt_uses_public_room_context_and_private_boundary(self):
        prompt = PromptBuilder.build_room_agent_reply_prompt(
            agent_name="AI",
            agent_personality="稳重",
            user_name="阿树",
            event_title="周六网球",
            match_summary="双方周六下午上海网球，新手友好，场地费 AA。",
            mentioned_by="阿树",
            user_memories=[("preference", "用户常在虹口活动，周六下午通常有空")],
            participants=["阿树", "小林", "AI(Agent)"],
            public_events_text=(
                "A: 周六网球｜上海｜徐汇｜2026-06-06 15:00-17:00\n"
                "B: 找人打网球｜上海｜徐汇或静安｜时间未确认"
            ),
            agent_dialogue="B: 我这边具体时间还需要用户确认。",
            recent_messages_text="阿树: @AI 能直接定周六下午吗？",
        )

        self.assertIn("双方公开事件、公开协商记录、匹配摘要、聊天室最近消息", prompt)
        self.assertIn("A: 周六网球", prompt)
        self.assertIn("B: 找人打网球", prompt)
        self.assertIn("我这边具体时间还需要用户确认", prompt)
        self.assertIn("用户常在虹口活动", prompt)
        self.assertIn("profile/memory 不能替代本次公开事件字段", prompt)
        self.assertIn("不能直接定，我这边时间还没公开确认，需要你本人先确认", prompt)
        self.assertIn("used_private_context", prompt)


if __name__ == "__main__":
    unittest.main()
