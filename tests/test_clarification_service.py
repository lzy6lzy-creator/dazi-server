from __future__ import annotations

import unittest
from datetime import date

from app.services.clarification_service import (
    merge_clarification_answers,
    normalize_clarification_payload,
)


class ClarificationServiceTests(unittest.TestCase):
    def test_normalize_payload_keeps_compact_valid_questions(self):
        payload = {
            "reply": "我把需要确认的点整理成卡片。",
            "needs_clarification": True,
            "draft": {"title": "上海街拍", "activity_type": "摄影"},
            "questions": [
                {
                    "id": "photo_style",
                    "type": "single_choice",
                    "title": "拍摄地点更偏向？",
                    "helper_text": "影响地点匹配和候选推荐。",
                    "category": "地点",
                    "required": False,
                    "allow_custom": True,
                    "options": [
                        {"id": "street", "label": "街拍", "value": "街拍"},
                        {"id": "park", "label": "公园", "value": "公园"},
                    ],
                }
            ],
        }

        result = normalize_clarification_payload(payload)

        self.assertEqual(result["reply"], "我把需要确认的点整理成卡片。")
        self.assertEqual(result["draft"]["title"], "上海街拍")
        self.assertEqual(len(result["questions"]), 1)
        self.assertEqual(result["questions"][0]["id"], "photo_style")
        self.assertEqual(result["questions"][0]["options"][0]["label"], "街拍")

    def test_normalize_payload_rejects_malformed_questions_safely(self):
        result = normalize_clarification_payload({
            "reply": "先聊聊。",
            "needs_clarification": True,
            "questions": [
                {"id": "missing_title", "options": [{"id": "a", "label": "A"}]},
                {"id": "missing_options", "title": "去哪？", "options": []},
            ],
        })

        self.assertEqual(result["reply"], "先聊聊。")
        self.assertEqual(result["questions"], [])

    def test_normalize_payload_sanitizes_malformed_draft_fields(self):
        result = normalize_clarification_payload({
            "reply": "我先确认几个点。",
            "needs_clarification": False,
            "draft": {
                "title": {"bad": "shape"},
                "activity_type": 123,
                "city": " 上海 ",
                "location": ["not", "a", "string"],
                "preferences": ["街拍", "", {"bad": "shape"}, " 胶片 "],
                "constraints": "不要是字符串",
                "unexpected": "drop me",
            },
        })

        self.assertEqual(result["draft"], {
            "city": "上海",
            "preferences": ["街拍", "胶片"],
            "constraints": [],
        })

    def test_merge_free_text_only_answer_into_preferences(self):
        merged = merge_clarification_answers(
            draft={"title": "上海街拍", "preferences": [], "constraints": []},
            questions=[],
            answers=[],
            user_birth_date=None,
            today=date(2026, 6, 4),
            free_text="  也可以接受胶片摄影  ",
        )

        self.assertEqual(merged["preferences"], ["也可以接受胶片摄影"])
        self.assertEqual(merged["constraints"], [])
        self.assertEqual(merged["clarification_answers"], [])

    def test_merge_age_answer_unlimited_does_not_store_filter(self):
        draft = {"title": "看电影", "preferences": [], "constraints": []}
        questions = [
            {
                "id": "age_range",
                "type": "age_range",
                "match_filter": "hard_filter",
                "options": [
                    {"id": "unlimited", "label": "不限制", "value": None},
                ],
            }
        ]

        merged = merge_clarification_answers(
            draft=draft,
            questions=questions,
            answers=[{"question_id": "age_range", "option_ids": ["unlimited"]}],
            user_birth_date=date(1998, 6, 4),
            today=date(2026, 6, 4),
        )

        self.assertNotIn("age_filter_min", merged)
        self.assertNotIn("age_filter_max", merged)
        self.assertNotIn("age_filter_mode", merged)
        self.assertEqual(merged["preferences"], [])

    def test_merge_age_answer_range_uses_user_age(self):
        draft = {"title": "徒步", "preferences": [], "constraints": []}
        questions = [
            {
                "id": "age_range",
                "type": "age_range",
                "match_filter": "hard_filter",
                "options": [
                    {"id": "plus_minus_5", "label": "±5 岁", "value": {"range": 5}},
                ],
            }
        ]

        merged = merge_clarification_answers(
            draft=draft,
            questions=questions,
            answers=[{"question_id": "age_range", "option_ids": ["plus_minus_5"]}],
            user_birth_date=date(1998, 6, 5),
            today=date(2026, 6, 4),
        )

        self.assertEqual(merged["age_filter_min"], 22)
        self.assertEqual(merged["age_filter_max"], 32)
        self.assertEqual(merged["age_filter_mode"], "hard_filter")
        self.assertIn("年龄范围 22-32 岁", merged["constraints"])

    def test_merge_custom_age_answer(self):
        merged = merge_clarification_answers(
            draft={"title": "咖啡", "preferences": [], "constraints": []},
            questions=[{"id": "age_range", "type": "age_range", "match_filter": "preference", "options": []}],
            answers=[{"question_id": "age_range", "custom_value": {"min_age": 23, "max_age": 32}}],
            user_birth_date=None,
            today=date(2026, 6, 4),
        )

        self.assertEqual(merged["age_filter_min"], 23)
        self.assertEqual(merged["age_filter_max"], 32)
        self.assertEqual(merged["age_filter_mode"], "preference")
        self.assertIn("年龄偏好 23-32 岁", merged["preferences"])


if __name__ == "__main__":
    unittest.main()
