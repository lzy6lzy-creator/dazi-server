import unittest

from experiments.location_matching.evaluate_event_location_vector import (
    augment_location_text,
    best_threshold_metrics,
    char_ngram_similarity,
    location_alias_score,
    location_containment_score,
    score_location_hybrid_text,
    merge_event_location,
)


class EventLocationVectorExperimentTest(unittest.TestCase):
    def test_merge_event_location_prefers_specific_location_over_city(self):
        event = {"city": "上海", "location": "浦东", "activity_type": "咖啡"}

        self.assertEqual(merge_event_location(event), "上海 浦东")

    def test_merge_event_location_falls_back_to_city(self):
        event = {"city": "台北", "location": None, "activity_type": "桌游"}

        self.assertEqual(merge_event_location(event), "台北")

    def test_augment_location_expands_region_for_vector_matching(self):
        text = augment_location_text("川西")

        self.assertIn("四姑娘山", text)
        self.assertIn("稻城亚丁", text)

    def test_char_ngram_similarity_scores_aliases_above_unrelated_places(self):
        self.assertGreater(
            char_ngram_similarity("上海 浦东", "上海 陆家嘴"),
            char_ngram_similarity("上海 浦东", "北京 朝阳"),
        )

    def test_best_threshold_metrics_selects_threshold_with_perfect_split(self):
        scores = [0.9, 0.8, 0.2, 0.1]
        labels = [True, True, False, False]

        metrics = best_threshold_metrics(scores, labels)

        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall"], 1.0)

    def test_location_containment_scores_region_covering_place(self):
        self.assertGreaterEqual(location_containment_score("江浙沪", "杭州 西湖"), 0.85)
        self.assertGreaterEqual(location_containment_score("川西", "四姑娘山"), 0.85)

    def test_location_alias_score_handles_common_equivalents(self):
        self.assertEqual(location_alias_score("大湾区", "粤港澳大湾区"), 1.0)
        self.assertGreaterEqual(location_alias_score("浦东新区", "上海 浦东"), 0.9)

    def test_location_hybrid_text_ignores_activity_context(self):
        source = {"activity_type": "咖啡", "eval_location": "江浙沪"}
        target = {"activity_type": "散步", "eval_location": "杭州 西湖"}

        self.assertGreaterEqual(score_location_hybrid_text(source, target), 0.85)

    def test_location_hybrid_text_keeps_unrelated_places_low(self):
        source = {"activity_type": "旅行", "eval_location": "大理 洱海"}
        target = {"activity_type": "旅行", "eval_location": "厦门 鼓浪屿"}

        self.assertLess(score_location_hybrid_text(source, target), 0.65)


if __name__ == "__main__":
    unittest.main()
