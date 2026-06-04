from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class FeedbackStaticTests(unittest.TestCase):
    def test_homepage_has_feedback_form_below_beta_signup(self):
        html = read_text("app/static/index.html")

        beta_index = html.find('id="betaSignupForm"')
        feedback_index = html.find('id="feedbackForm"')

        self.assertNotEqual(-1, beta_index)
        self.assertNotEqual(-1, feedback_index)
        self.assertGreater(feedback_index, beta_index)
        self.assertIn("/api/v1/feedback", html)
        self.assertIn('name="category"', html)
        self.assertIn('name="content"', html)
        self.assertIn('name="contact"', html)
        self.assertIn("提交反馈", html)

    def test_backend_declares_public_feedback_route_and_model(self):
        feedback_api = ROOT / "app/api/feedback.py"
        feedback_model = ROOT / "app/models/site_feedback.py"
        main = read_text("app/main.py")

        self.assertTrue(feedback_api.exists())
        self.assertTrue(feedback_model.exists())
        self.assertIn('@router.post("/feedback"', feedback_api.read_text(encoding="utf-8"))
        self.assertIn('__tablename__ = "site_feedback"', feedback_model.read_text(encoding="utf-8"))
        self.assertIn("from app.api.feedback import router as feedback_router", main)
        self.assertIn("app.include_router(feedback_router)", main)
        self.assertIn("from app.models.site_feedback import SiteFeedback", main)

    def test_admin_can_view_and_export_feedback(self):
        admin_api = read_text("app/api/admin.py")
        admin_html = read_text("app/static/admin.html")

        self.assertIn("SiteFeedback", admin_api)
        self.assertIn('@router.get("/feedback")', admin_api)
        self.assertIn('@router.get("/feedback.csv")', admin_api)
        self.assertIn('data-panel="feedback"', admin_html)
        self.assertIn('id="panel-feedback"', admin_html)
        self.assertIn("/api/admin/feedback", admin_html)
        self.assertIn("/api/admin/feedback.csv", admin_html)
        self.assertIn("downloadFeedbackCsv", admin_html)

    def test_admin_can_update_feedback_status(self):
        admin_api = read_text("app/api/admin.py")
        admin_html = read_text("app/static/admin.html")

        self.assertIn('@router.patch("/feedback/{feedback_id}/status")', admin_api)
        self.assertIn("FeedbackStatusUpdate", admin_api)
        self.assertIn("setFeedbackStatus", admin_html)
        self.assertIn("data-feedback-status", admin_html)
        self.assertIn("已处理", admin_html)


if __name__ == "__main__":
    unittest.main()
