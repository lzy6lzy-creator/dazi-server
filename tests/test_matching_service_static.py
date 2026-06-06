from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MatchingServiceStaticTests(unittest.TestCase):
    def test_matching_service_blocklists_a2a_failed_pairs(self):
        text = (ROOT / "app" / "services" / "matching_service.py").read_text(encoding="utf-8")

        self.assertIn("add_match_blocklist", text)
        self.assertIn("_blocklist_evaluated_pairs", text)
        self.assertIn('reason="a2a_rejected"', text)
        self.assertIn("await self._blocklist_evaluated_pairs(event, all_evaluations, db)", text)

    def test_a2a_chat_room_creation_pushes_room_created_notification(self):
        text = (ROOT / "app" / "services" / "matching_service.py").read_text(encoding="utf-8")

        create_room_body = text.split("async def _create_chat_room", 1)[1]
        self.assertIn('"type": "room_created"', create_room_body)
        self.assertIn('"room_id": str(room.id)', create_room_body)

    def test_push_notification_failure_does_not_abort_room_creation(self):
        text = (ROOT / "app" / "services" / "matching_service.py").read_text(encoding="utf-8")

        create_room_body = text.split("async def _create_chat_room", 1)[1]
        self.assertIn("try:", create_room_body)
        self.assertIn("push_notification_service.send_to_users", create_room_body)
        self.assertIn("except Exception", create_room_body)
        self.assertIn("logger.warning", create_room_body)

    def test_match_preview_includes_current_matched_event(self):
        text = (ROOT / "app" / "services" / "matching_service.py").read_text(encoding="utf-8")

        preview_body = text.split("async def preview_match", 1)[1].split(
            "def _post_filter_detailed",
            1,
        )[0]
        self.assertIn("matched_event = await self._matched_event_for_preview(event, db)", preview_body)
        self.assertIn('"matched_event": matched_event', preview_body)
        self.assertIn("async def _matched_event_for_preview", text)
        self.assertIn('"status": "matched_pair"', text)

    def test_matching_post_filter_uses_age_and_gender_score_adjustments(self):
        text = (ROOT / "app" / "services" / "matching_service.py").read_text(encoding="utf-8")
        post_filter_body = text.split("async def _post_filter", 1)[1].split(
            "async def _user_profiles_for_events",
            1,
        )[0]

        self.assertIn("is_gender_filter_compatible", post_filter_body)
        self.assertIn("adjusted_candidate_score", post_filter_body)
        self.assertIn("gender_decision.should_pass", post_filter_body)
        self.assertIn("filtered.sort(key=lambda item: item[1], reverse=True)", post_filter_body)

    def test_match_preview_reports_gender_filtered_candidates(self):
        text = (ROOT / "app" / "services" / "matching_service.py").read_text(encoding="utf-8")
        detailed_body = text.split("def _post_filter_detailed", 1)[1].split(
            "@staticmethod",
            1,
        )[0]

        self.assertIn("is_gender_filter_compatible", detailed_body)
        self.assertIn('status = "gender_filtered"', detailed_body)
        self.assertIn("adjusted_candidate_score", detailed_body)


if __name__ == "__main__":
    unittest.main()
