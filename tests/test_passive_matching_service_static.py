from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PassiveMatchingServiceStaticTests(unittest.TestCase):
    def test_passive_blocklist_is_scoped_to_event_and_candidate_user(self):
        text = (ROOT / "app" / "services" / "passive_matching_service.py").read_text(encoding="utf-8")

        blocklist_clause = text.split("SELECT 1 FROM match_blocklists mb", 1)[1].split("ORDER BY", 1)[0]

        self.assertIn("(mb.event_a_id = :event_id OR mb.event_b_id = :event_id)", blocklist_clause)
        self.assertIn("(mb.user_a_id = :event_user_id AND mb.user_b_id = u.id)", blocklist_clause)
        self.assertIn("(mb.user_b_id = :event_user_id AND mb.user_a_id = u.id)", blocklist_clause)
        self.assertNotIn("WHERE mb.event_a_id = :event_id\n                     OR mb.event_b_id = :event_id", blocklist_clause)

    def test_passive_recall_uses_gender_filter_and_adjusted_score(self):
        text = (ROOT / "app" / "services" / "passive_matching_service.py").read_text(encoding="utf-8")

        self.assertIn("u.gender", text)
        self.assertIn("is_gender_filter_compatible", text)
        self.assertIn("adjusted_candidate_score", text)
        self.assertIn("gender_decision.should_pass", text)
        self.assertIn("if adjusted_similarity < PASSIVE_VECTOR_THRESHOLD", text)
        self.assertIn("candidates.sort(key=lambda item: item[1], reverse=True)", text)
        self.assertIn("chosen, similarity = candidates[0]", text)


if __name__ == "__main__":
    unittest.main()
