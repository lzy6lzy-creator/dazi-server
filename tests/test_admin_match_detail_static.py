from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminMatchDetailStaticTests(unittest.TestCase):
    def test_admin_api_exposes_match_pair_detail(self):
        source = (ROOT / "app" / "api" / "admin.py").read_text(encoding="utf-8")

        self.assertIn('@router.get("/match/detail/{event_id}/{candidate_id}")', source)
        self.assertIn("MatchLog.event_a_id == event_id", source)
        self.assertIn("MatchLog.event_b_id == candidate_id", source)
        self.assertIn('"dialogue_log"', source)
        self.assertIn('"score_breakdown"', source)
        self.assertIn('"blocklists"', source)

    def test_admin_preview_candidate_rows_open_detail_modal(self):
        html = (ROOT / "app" / "static" / "admin.html").read_text(encoding="utf-8")

        self.assertIn("openMatchDetail(", html)
        self.assertIn("state.matchDetailCandidates[cacheKey] = candidate", html)
        self.assertIn("detailAction", html)
        self.assertIn("/api/admin/match/detail/", html)
        self.assertIn("renderMatchDetail(data, candidate)", html)
        self.assertIn("renderScoreBreakdown(", html)
        self.assertIn("A2A 对话", html)
        self.assertIn("细项分数", html)
        self.assertIn("匹配日志", html)


if __name__ == "__main__":
    unittest.main()
