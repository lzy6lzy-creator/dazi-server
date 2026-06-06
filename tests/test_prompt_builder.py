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

    def test_conversation_orchestrator_prompt_includes_state_and_tag_actions(self):
        prompt = PromptBuilder.build_conversation_orchestrator_prompt(
            user_name="小明",
            user_city="上海",
            current_location="上海 徐汇区",
            user_interests=["火锅"],
            user_bio="",
            birth_date=None,
            memories=[("constraint", "不吃辣")],
            conversation_state="当前已有待确认活动草稿",
        )

        self.assertIn("chat|clarify|draft|cancel", prompt)
        self.assertIn("<reply>", prompt)
        self.assertIn("<question_json>", prompt)
        self.assertIn("逐项输出", prompt)
        self.assertIn("## 当前时间", prompt)
        self.assertIn("当前已有待确认活动草稿", prompt)
        self.assertIn("当前位置：上海 徐汇区", prompt)
        self.assertIn("不吃辣", prompt)
        self.assertNotIn('"city"', prompt)
        self.assertNotIn("[EVENT_DRAFT]", prompt)
        self.assertNotIn("[EVENT_READY]", prompt)

    def test_conversation_orchestrator_prompt_uses_location_only_gate_rules(self):
        prompt = PromptBuilder.build_conversation_orchestrator_prompt(
            user_name="小明",
            current_location="上海 徐汇区",
            user_interests=["网球"],
            user_bio="",
            birth_date="1998-06-05",
            memories=[],
            conversation_state="无待处理状态",
        )

        self.assertIn("action 必须是 clarify，而不是 draft", prompt)
        self.assertIn("服务端不会用规则补 event/time/location/gender/preferences", prompt)
        self.assertIn("不要依赖服务端补字段", prompt)
        self.assertIn("如果地点未明确", prompt)
        self.assertIn("用户明确提到地点时，以用户表述为准", prompt)
        self.assertIn("只使用 location 一个地点槽位", prompt)
        self.assertNotIn("id=city", prompt)
        self.assertNotIn("draft.city", prompt)
        self.assertIn("time 永远展示", prompt)
        self.assertIn("不是服务端固定默认时间", prompt)
        self.assertIn("新手也行", prompt)
        self.assertIn("场地费 AA", prompt)

    def test_conversation_orchestrator_prompt_includes_age_and_gender_cards(self):
        prompt = PromptBuilder.build_conversation_orchestrator_prompt(
            user_name="小明",
            current_location="上海 徐汇区",
            user_interests=["电影"],
            user_bio="",
            birth_date="1998-06-05",
            memories=[],
            conversation_state="无待处理状态",
        )

        self.assertIn("年龄和性别是常规匹配确认项", prompt)
        self.assertIn("id=age", prompt)
        self.assertIn("type=age_range", prompt)
        self.assertIn("-5 到 +5", prompt)
        self.assertIn("default_option_ids", prompt)
        self.assertIn("男、女、优先男、优先女、不限", prompt)
        self.assertIn("不再重复展示 gender 卡片", prompt)
        self.assertIn("id=gender", prompt)
        self.assertIn("用户自己的 profile gender 不能替代本次活动的搭子性别偏好", prompt)

    def test_conversation_orchestrator_prompt_combines_extraction_with_default_cards(self):
        prompt = PromptBuilder.build_conversation_orchestrator_prompt(
            user_name="小明",
            current_location="上海 徐汇区",
            user_interests=["电影"],
            user_bio="",
            birth_date=None,
            memories=[],
            conversation_state="无待处理状态",
        )

        self.assertIn("clarify 同时做信息抽取和结构化确认", prompt)
        self.assertIn("不要限制 questions 数量", prompt)
        self.assertIn("default_option_ids", prompt)
        self.assertIn("start_time 和 end_time", prompt)
        self.assertIn("LLM 要根据用户表达推断具体 start_time/end_time", prompt)
        self.assertIn("前端固定默认时间", prompt)
        self.assertIn("小/中/大多个候选", prompt)

    def test_draft_prompt_builder_outputs_tag_format(self):
        prompt = PromptBuilder.build_event_draft_prompt(
            user_name="小明",
            current_location="上海市徐汇区",
            original_message="周六晚上想打羽毛球，女生优先",
            draft_seed={"activity_type": "羽毛球", "preferences": ["女生优先"]},
            questions=[{"id": "time", "title": "时间", "options": []}],
            answers=[{"question_id": "time", "custom_value": {"start_time": "2026-06-06T19:00:00+08:00", "end_time": "2026-06-06T21:00:00+08:00"}}],
            free_text=None,
        )

        self.assertIn("生成最终事件草稿", prompt)
        self.assertIn("<draft_reply>", prompt)
        self.assertIn("<draft_json>", prompt)
        self.assertIn("周六晚上想打羽毛球", prompt)
        self.assertIn("女生优先", prompt)

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
