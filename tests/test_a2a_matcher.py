from __future__ import annotations

import unittest
from uuid import uuid4

from app.services.a2a_matcher import A2AMatcher, parse_a2a_response
from app.services.prompt_builder import PromptBuilder


class A2AMatcherTests(unittest.TestCase):
    def test_parse_a2a_response_normalizes_dialogue_and_match_decision(self):
        source_id = uuid4()
        candidate_id = uuid4()
        parsed = parse_a2a_response(
            source_event_id=source_id,
            candidate_event_id=candidate_id,
            payload={
                "dialogue": [
                    {"speaker": "点点", "content": "时间都在周六下午。"},
                    {"speaker": "圆圆", "content": "都想看科幻片。"},
                ],
                "compatibility": 0.82,
                "should_match": True,
                "has_blocking_conflict": False,
                "match_reasons": ["时间匹配", "偏好一致"],
                "potential_issues": ["地点还要确认"],
                "score_breakdown": [
                    {"dimension": "time", "score": 0.9, "reason": "时间重叠", "blocking": False},
                    {"dimension": "preference", "score": "0.8", "reason": "偏好接近", "blocking": False},
                ],
                "chatroom_carryover": "已确认周六下午看电影，时间地点合适。",
                "summary": "两人都想看科幻片，时间合适。",
            },
        )

        self.assertEqual(parsed.source_event_id, source_id)
        self.assertEqual(parsed.candidate_event_id, candidate_id)
        self.assertEqual(parsed.compatibility, 0.82)
        self.assertTrue(parsed.should_match)
        self.assertEqual(parsed.reasons, ["时间匹配", "偏好一致"])
        self.assertEqual(parsed.issues, ["地点还要确认"])
        self.assertEqual(parsed.score_breakdown[0]["dimension"], "time")
        self.assertEqual(parsed.score_breakdown[0]["score"], 0.9)
        self.assertEqual(parsed.score_breakdown[1]["score"], 0.8)
        self.assertEqual(parsed.summary, "已确认周六下午看电影，时间地点合适。")
        self.assertIn("点点: 时间都在周六下午。", parsed.dialogue_log)

    def test_parse_a2a_response_rejects_low_or_missing_payload(self):
        source_id = uuid4()
        candidate_id = uuid4()

        low = parse_a2a_response(source_id, candidate_id, {"compatibility": 0.3, "summary": "兴趣不同"})
        missing = parse_a2a_response(source_id, candidate_id, None)

        self.assertFalse(low.should_match)
        self.assertEqual(low.compatibility, 0.3)
        self.assertFalse(missing.should_match)
        self.assertEqual(missing.compatibility, 0.0)

    def test_parse_a2a_response_accepts_only_scores_at_or_above_seventy(self):
        source_id = uuid4()
        candidate_id = uuid4()

        below = parse_a2a_response(source_id, candidate_id, {"compatibility": 0.69, "should_match": True})
        at_threshold = parse_a2a_response(source_id, candidate_id, {"compatibility": 0.70, "should_match": True})

        self.assertFalse(below.should_match)
        self.assertTrue(at_threshold.should_match)

    def test_parse_a2a_response_rejects_blocking_conflict_even_with_high_score(self):
        source_id = uuid4()
        candidate_id = uuid4()
        parsed = parse_a2a_response(
            source_id,
            candidate_id,
            {
                "compatibility": 0.95,
                "should_match": True,
                "has_blocking_conflict": True,
                "conflicts": ["技能水平冲突"],
                "uncertainties": ["地点未确认"],
                "summary": "冲突但高分",
            },
        )

        self.assertFalse(parsed.should_match)
        self.assertEqual(parsed.issues, ["技能水平冲突", "地点未确认"])

    def test_a2a_prompt_uses_v6_contract_and_unknown_field_rules(self):
        prompt = PromptBuilder.build_a2a_dialogue_prompt()

        self.assertIn("mode=agent_turn", prompt)
        self.assertIn("mode=judge", prompt)
        self.assertIn("不可变信息边界", prompt)
        self.assertIn("公开事件中 `start_time` 或 `end_time` 为 null", prompt)
        self.assertIn("compatibility>=0.70", prompt)
        self.assertIn("score_breakdown", prompt)
        self.assertIn("鸳鸯锅", prompt)
        self.assertIn("不是硬冲突", prompt)
        self.assertIn("具体店铺", prompt)
        self.assertIn("不要放入 `uncertainties`", prompt)
        self.assertIn("chatroom_carryover", prompt)

    def test_agent_payload_only_contains_self_private_memory(self):
        payload = A2AMatcher._build_agent_turn_payload(
            side="A",
            task="开场",
            public_events={"A": {"title": "咖啡"}, "B": {"title": "网球"}},
            dialogue=[],
            self_private={
                "profile": {"city": "上海"},
                "memory": ["A 私有记忆"],
            },
        )

        text = str(payload)
        self.assertIn("A 私有记忆", text)
        self.assertNotIn("B 私有记忆", text)
        self.assertEqual(payload["mode"], "agent_turn")

    def test_judge_payload_excludes_private_memory(self):
        payload = A2AMatcher._build_judge_payload(
            public_events={"A": {"title": "咖啡"}, "B": {"title": "网球"}},
            dialogue=[{"speaker": "A", "content": "公开对话"}],
        )

        text = str(payload)
        self.assertIn("公开对话", text)
        self.assertNotIn("私有记忆", text)
        self.assertEqual(payload["mode"], "judge")


if __name__ == "__main__":
    unittest.main()
