from __future__ import annotations

import unittest
from datetime import date

from app.services.clarification_service import (
    merge_clarification_answers,
    normalize_conversation_payload,
    normalize_clarification_payload,
    normalize_draft_payload,
)


class ClarificationServiceTests(unittest.TestCase):
    def test_normalize_draft_payload_accepts_reply_and_draft(self):
        result = normalize_draft_payload({
            "reply": "我整理好了，确认后就发布。",
            "draft": {
                "title": "周六羽毛球",
                "activity_type": "羽毛球",
                "location": "上海市徐汇区",
                "start_time": "2026-06-06T19:00:00+08:00",
                "end_time": "2026-06-06T21:00:00+08:00",
                "preferences": ["女生优先", "中等水平"],
                "constraints": [],
            },
        })

        self.assertEqual(result["reply"], "我整理好了，确认后就发布。")
        self.assertEqual(result["draft"]["activity_type"], "羽毛球")
        self.assertEqual(result["draft"]["preferences"], ["女生优先", "中等水平"])

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

    def test_normalize_payload_keeps_all_questions_and_default_option_ids(self):
        result = normalize_conversation_payload({
            "action": "clarify",
            "reply": "我先确认几个点。",
            "questions": [
                {"id": "gender", "title": "搭子性别偏好？", "options": [{"id": "any", "label": "不限"}]},
                {"id": "time", "title": "几点方便？", "options": [{"id": "night", "label": "晚上"}]},
                {"id": "skill", "title": "水平要求？", "options": [{"id": "any", "label": "都行"}]},
                {"id": "cost", "title": "费用怎么分？", "options": [{"id": "aa", "label": "AA"}]},
                {
                    "id": "preference",
                    "title": "特殊偏好？",
                    "default_option_ids": ["quiet"],
                    "options": [{"id": "quiet", "label": "安静一点", "value": "安静一点"}],
                },
            ],
        })

        self.assertEqual([q["id"] for q in result["questions"]], ["gender", "time", "skill", "cost", "preference"])
        self.assertEqual(result["questions"][-1]["default_option_ids"], ["quiet"])

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
            "location": "上海",
            "preferences": ["街拍", "胶片"],
            "constraints": [],
        })

    def test_normalize_conversation_payload_uses_location_as_single_place_slot(self):
        result = normalize_conversation_payload({
            "action": "draft",
            "reply": "整理好了。",
            "draft": {
                "title": "周六电影",
                "activity_type": "看电影",
                "city": "上海",
                "location": "",
                "preferences": ["周六下午"],
                "constraints": ["上海"],
            },
        })

        self.assertEqual(result["draft"]["location"], "上海")
        self.assertNotIn("city", result["draft"])
        self.assertEqual(result["draft"]["constraints"], [])

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

    def test_merge_generic_answer_prefers_string_option_value_for_draft_text(self):
        merged = merge_clarification_answers(
            draft={"title": "网球", "preferences": [], "constraints": []},
            questions=[
                {
                    "id": "cost",
                    "type": "single_choice",
                    "match_filter": "preference",
                    "options": [
                        {"id": "aa", "label": "AA 平摊", "value": "场地费 AA"},
                    ],
                }
            ],
            answers=[{"question_id": "cost", "option_ids": ["aa"]}],
            user_birth_date=None,
            today=date(2026, 6, 4),
        )

        self.assertEqual(merged["preferences"], ["场地费 AA"])

    def test_merge_default_field_card_answer_updates_draft_fields(self):
        merged = merge_clarification_answers(
            draft={"title": "周日下午看电影", "preferences": [], "constraints": []},
            questions=[
                {
                    "id": "event",
                    "type": "single_choice",
                    "options": [
                        {"id": "movie", "label": "看电影", "value": {"activity_type": "看电影"}},
                    ],
                },
                {
                    "id": "time",
                    "type": "single_choice",
                    "options": [
                        {
                            "id": "sun_afternoon",
                            "label": "周日 14:00-17:00",
                            "value": {
                                "start_time": "2026-06-07T14:00:00+08:00",
                                "end_time": "2026-06-07T17:00:00+08:00",
                            },
                        },
                    ],
                },
            ],
            answers=[
                {"question_id": "event", "option_ids": ["movie"]},
                {"question_id": "time", "option_ids": ["sun_afternoon"]},
            ],
            user_birth_date=None,
            today=date(2026, 6, 5),
        )

        self.assertEqual(merged["activity_type"], "看电影")
        self.assertEqual(merged["start_time"], "2026-06-07T14:00:00+08:00")
        self.assertEqual(merged["end_time"], "2026-06-07T17:00:00+08:00")
        self.assertEqual(merged["preferences"], [])

    def test_merge_time_custom_value_updates_start_and_end_time(self):
        merged = merge_clarification_answers(
            draft={"title": "周日下午看电影", "preferences": [], "constraints": []},
            questions=[
                {
                    "id": "time",
                    "type": "single_choice",
                    "options": [
                        {
                            "id": "default_time",
                            "label": "周日 14:00-17:00",
                            "value": {
                                "start_time": "2026-06-07T14:00:00+08:00",
                                "end_time": "2026-06-07T17:00:00+08:00",
                            },
                        },
                    ],
                },
            ],
            answers=[
                {
                    "question_id": "time",
                    "option_ids": ["default_time"],
                    "custom_value": {
                        "start_time": "2026-06-07T15:00:00+08:00",
                        "end_time": "2026-06-07T18:00:00+08:00",
                    },
                },
            ],
            user_birth_date=None,
            today=date(2026, 6, 5),
        )

        self.assertEqual(merged["start_time"], "2026-06-07T15:00:00+08:00")
        self.assertEqual(merged["end_time"], "2026-06-07T18:00:00+08:00")
        self.assertEqual(merged["preferences"], [])

    def test_merge_gender_answer_records_partner_gender_preference(self):
        merged = merge_clarification_answers(
            draft={"title": "看电影", "preferences": [], "constraints": []},
            questions=[
                {
                    "id": "gender",
                    "type": "single_choice",
                    "match_filter": "preference",
                    "options": [
                        {"id": "female_preferred", "label": "女生优先", "value": "搭子性别偏好：女生优先"},
                    ],
                }
            ],
            answers=[{"question_id": "gender", "option_ids": ["female_preferred"]}],
            user_birth_date=None,
            today=date(2026, 6, 5),
        )

        self.assertEqual(merged["preferences"], ["搭子性别偏好：女生优先"])
        self.assertEqual(merged["constraints"], [])

    def test_merge_gender_answer_supports_strict_and_preferred_options(self):
        questions = [
            {
                "id": "gender",
                "type": "single_choice",
                "match_filter": "preference",
                "options": [
                    {"id": "male", "label": "男", "value": {"constraints": ["搭子性别：男"]}},
                    {"id": "female_preferred", "label": "优先女", "value": {"preferences": ["搭子性别偏好：女生优先"]}},
                ],
            }
        ]

        strict = merge_clarification_answers(
            draft={"title": "看电影", "preferences": [], "constraints": []},
            questions=questions,
            answers=[{"question_id": "gender", "option_ids": ["male"]}],
            user_birth_date=None,
            today=date(2026, 6, 5),
        )
        preferred = merge_clarification_answers(
            draft={"title": "看电影", "preferences": [], "constraints": []},
            questions=questions,
            answers=[{"question_id": "gender", "option_ids": ["female_preferred"]}],
            user_birth_date=None,
            today=date(2026, 6, 5),
        )

        self.assertEqual(strict["constraints"], ["搭子性别：男"])
        self.assertEqual(strict["preferences"], [])
        self.assertEqual(preferred["preferences"], ["搭子性别偏好：女生优先"])
        self.assertEqual(preferred["constraints"], [])

    def test_merge_location_question_writes_location_not_constraints(self):
        merged = merge_clarification_answers(
            draft={"title": "看电影", "preferences": [], "constraints": []},
            questions=[
                {
                    "id": "city",
                    "type": "single_choice",
                    "category": "地点",
                    "match_filter": "hard_filter",
                    "options": [
                        {"id": "shanghai", "label": "上海", "value": "上海"},
                    ],
                }
            ],
            answers=[{"question_id": "city", "option_ids": ["shanghai"]}],
            user_birth_date=None,
            today=date(2026, 6, 5),
        )

        self.assertEqual(merged["location"], "上海")
        self.assertEqual(merged["preferences"], [])
        self.assertEqual(merged["constraints"], [])

    def test_merge_area_custom_answer_writes_location(self):
        merged = merge_clarification_answers(
            draft={"title": "看电影", "preferences": [], "constraints": []},
            questions=[
                {
                    "id": "area",
                    "type": "single_choice",
                    "category": "地点",
                    "match_filter": "preference",
                    "options": [
                        {"id": "xuhui", "label": "徐汇", "value": "徐汇"},
                    ],
                }
            ],
            answers=[{"question_id": "area", "custom_value": "徐汇/静安"}],
            user_birth_date=None,
            today=date(2026, 6, 5),
        )

        self.assertEqual(merged["location"], "徐汇/静安")
        self.assertEqual(merged["preferences"], [])
        self.assertEqual(merged["constraints"], [])

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

    def test_normalize_draft_payload_preserves_age_filter_fields(self):
        result = normalize_draft_payload({
            "reply": "草稿好了。",
            "draft": {
                "title": "咖啡",
                "activity_type": "咖啡",
                "age_filter_min": 23,
                "age_filter_max": 32,
                "age_filter_mode": "preference",
            },
        })

        self.assertEqual(result["draft"]["age_filter_min"], 23)
        self.assertEqual(result["draft"]["age_filter_max"], 32)
        self.assertEqual(result["draft"]["age_filter_mode"], "preference")

    def test_normalize_conversation_payload_preserves_draft_and_questions(self):
        payload = {
            "action": "clarify",
            "reply": "我先确认两个点。",
            "draft": {
                "title": "今晚火锅",
                "activity_type": "火锅",
                "city": "上海",
                "start_time": "2026-06-05T19:00:00",
                "end_time": "2026-06-05T21:00:00",
                "preferences": ["实惠"],
                "constraints": ["不吃辣"],
            },
            "questions": [
                {
                    "id": "budget",
                    "type": "single_choice",
                    "title": "人均预算？",
                    "options": [
                        {"id": "low", "label": "50-80", "value": "50-80"},
                    ],
                }
            ],
        }

        result = normalize_conversation_payload(payload)

        self.assertEqual(result["action"], "clarify")
        self.assertEqual(result["reply"], "我先确认两个点。")
        self.assertEqual(result["draft"]["location"], "上海")
        self.assertNotIn("city", result["draft"])
        self.assertEqual(result["draft"]["start_time"], "2026-06-05T19:00:00")
        self.assertEqual(result["draft"]["constraints"], ["不吃辣"])
        self.assertEqual(result["questions"][0]["id"], "budget")

    def test_normalize_conversation_payload_defaults_unknown_action_to_chat(self):
        result = normalize_conversation_payload({"action": "publish_now", "reply": "先聊聊"})

        self.assertEqual(result["action"], "chat")
        self.assertEqual(result["reply"], "先聊聊")
        self.assertEqual(result["draft"], {})
        self.assertEqual(result["questions"], [])


if __name__ == "__main__":
    unittest.main()
