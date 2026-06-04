from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminResetStaticTests(unittest.TestCase):
    def test_single_event_reset_clears_match_blocklists(self):
        text = (ROOT / "app" / "api" / "admin.py").read_text(encoding="utf-8")

        self.assertIn("delete(MatchBlocklist)", text)
        self.assertIn("MatchBlocklist.event_a_id == event_id", text)
        self.assertIn("MatchBlocklist.event_b_id == event_id", text)

    def test_reset_all_clears_match_blocklists(self):
        text = (ROOT / "app" / "api" / "admin.py").read_text(encoding="utf-8")

        self.assertIn("await db.execute(delete(MatchBlocklist))", text)


if __name__ == "__main__":
    unittest.main()
