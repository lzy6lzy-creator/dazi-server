from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminConsoleStaticTests(unittest.TestCase):
    def admin_html(self) -> str:
        return (ROOT / "app/static/admin.html").read_text(encoding="utf-8")

    def test_match_test_route_reuses_unified_admin_console(self):
        source = (ROOT / "app/main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        route_return = None
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "match_test_page":
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Call) and getattr(stmt.func, "id", None) == "FileResponse":
                        route_return = stmt.args[0].value

        self.assertEqual(route_return, "app/static/admin.html")

    def test_admin_console_contains_test_lab_with_shared_auth(self):
        html = self.admin_html()

        self.assertIn('id="adminToken"', html)
        self.assertIn("localStorage", html)
        self.assertIn('data-panel="testlab"', html)
        self.assertIn("/api/admin/test/generate", html)
        self.assertIn("/api/admin/test/match-preview-all", html)
        self.assertIn("/api/admin/test/stats", html)
        self.assertIn("/api/admin/test/cleanup", html)

    def test_admin_preview_uses_current_matching_preview_contract(self):
        html = self.admin_html()

        self.assertIn("total_recalled", html)
        self.assertIn("total_passed", html)
        self.assertIn("city_normalized", html)
        self.assertIn("candidates", html)
        self.assertIn("similarity", html)
        self.assertIn("filter_reason", html)
        self.assertNotIn("data.thresholds", html)
        self.assertNotIn("data.pipeline", html)
        self.assertNotIn("coarse_rank_top10", html)

    def test_matching_preview_selects_can_show_matched_events(self):
        html = self.admin_html()

        self.assertIn("eventOptions", html)
        self.assertIn("loadEventOptions", html)
        self.assertIn("requestAdmin('/api/admin/events')", html)
        self.assertIn("const source = state.eventOptions.length ? state.eventOptions : state.events", html)
        self.assertNotIn("previewEventSelect'].forEach", html)

    def test_matching_preview_renders_current_matched_event(self):
        html = self.admin_html()

        self.assertIn("renderMatchedEventPreview(data.matched_event, event.id)", html)
        self.assertIn("function renderMatchedEventPreview", html)
        self.assertIn("已匹配事件", html)
        self.assertIn("matched_pair", html)
        self.assertIn("当前已匹配", html)

    def test_dangerous_admin_actions_require_confirmation(self):
        html = self.admin_html()

        for action in [
            "matchAll",
            "resetAllEvents",
            "generateTestData",
            "cleanupTestData",
        ]:
            marker = f"async function {action}"
            start = html.index(marker)
            end = html.find("async function ", start + len(marker))
            block = html[start:] if end == -1 else html[start:end]
            self.assertIn("confirmAction", block, action)


if __name__ == "__main__":
    unittest.main()
