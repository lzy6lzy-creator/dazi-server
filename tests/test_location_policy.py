from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.services.location_normalizer import (
    align_city_from_catalog,
    cities_for_region,
    find_city,
    normalize_place,
    region_contains_city,
)
from app.services.location_policy import is_location_compatible


class LocationPolicyTests(unittest.TestCase):
    def test_normalize_region_landmark_online_and_flexible_places(self):
        chuanxi = normalize_place(activity_type="徒步", city="成都", location="川西")
        siguniang = normalize_place(activity_type="自驾", city=None, location="四姑娘山")
        online = normalize_place(activity_type="线上聊天", city=None, location="线上")
        flexible = normalize_place(activity_type="闲聊", city=None, location="不限地点")

        self.assertEqual(chuanxi.place_kind, "region")
        self.assertEqual(chuanxi.place_normalized, "川西")
        self.assertIsNone(chuanxi.admin_city)
        self.assertEqual(chuanxi.admin_region, "四川")
        self.assertEqual(chuanxi.geo_scope, "travel")

        self.assertEqual(siguniang.place_kind, "landmark")
        self.assertEqual(siguniang.place_normalized, "四姑娘山")
        self.assertEqual(siguniang.admin_region, "四川")

        self.assertEqual(online.geo_scope, "none")
        self.assertEqual(flexible.place_kind, "flexible")

    def test_strict_activity_blocks_cross_city_region_but_loose_activity_allows_it(self):
        strict = is_location_compatible(
            {"activity_type": "咖啡", "city": "上海", "location": "江浙沪"},
            {"activity_type": "咖啡", "city": "杭州", "location": "西湖"},
        )
        loose = is_location_compatible(
            {"activity_type": "周边游", "city": "上海", "location": "江浙沪"},
            {"activity_type": "旅行", "city": "杭州", "location": "西湖"},
        )

        self.assertFalse(strict.should_pass)
        self.assertEqual(strict.relation, "strict_cross_city")
        self.assertTrue(loose.should_pass)
        self.assertIn(loose.relation, {"city_in_region", "same_region"})

    def test_city_alias_and_region_city_links_come_from_location_catalog(self):
        self.assertEqual(find_city("魔都"), "上海")
        self.assertEqual(find_city("蓉城太古里"), "成都")
        self.assertEqual(find_city("羊城天河"), "广州")
        self.assertEqual(find_city("鹏城南山"), "深圳")

        self.assertTrue(region_contains_city("香港", "大湾区"))
        self.assertTrue(region_contains_city("苏州", "江浙沪"))
        self.assertTrue(region_contains_city("天津", "北京周边"))
        self.assertIn("香港", cities_for_region("粤港澳大湾区"))

    def test_city_alignment_uses_location_catalog_before_embedding(self):
        self.assertEqual(align_city_from_catalog("魔都"), "上海")
        self.assertEqual(align_city_from_catalog("蓉城"), "成都")
        self.assertEqual(align_city_from_catalog("羊城"), "广州")
        self.assertEqual(align_city_from_catalog("鹏城"), "深圳")
        self.assertEqual(align_city_from_catalog("北京周边"), "北京")

    def test_eval_dataset_passes_hybrid_policy_expectations(self):
        cases_path = Path(__file__).resolve().parents[1] / "experiments" / "location_matching" / "location_eval_cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))["match_cases"]

        mistakes = []
        for case in cases:
            decision = is_location_compatible(case["source"], case["target"])
            if decision.should_pass != case["expected"]["should_pass"]:
                mistakes.append((case["id"], case["expected"], decision))

        self.assertEqual(mistakes, [])


if __name__ == "__main__":
    unittest.main()
