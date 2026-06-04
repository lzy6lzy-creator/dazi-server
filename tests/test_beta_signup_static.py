from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class BetaSignupStaticTests(unittest.TestCase):
    def test_homepage_has_real_beta_signup_form(self):
        html = read_text("app/static/index.html")

        self.assertIn('id="betaSignupForm"', html)
        self.assertIn("/api/v1/beta-signups", html)
        self.assertIn("Apple ID 邮箱", html)
        self.assertIn('name="name"', html)
        self.assertIn('name="email"', html)
        self.assertIn('name="contact"', html)
        self.assertIn('name="contact" autocomplete="tel" type="tel"', html)
        self.assertIn('placeholder="11 位手机号，用作登录 app 的账号"', html)
        self.assertNotIn("方便联系确认", html)
        self.assertIn('pattern="1[3-9][0-9]{9}"', html)
        self.assertIn('name="device"', html)
        self.assertIn('name="activity_interests"', html)
        self.assertIn('name="consent"', html)
        self.assertIn('<span class="label-hint">上海优先</span>', html)
        self.assertIn('name="city" autocomplete="address-level2" maxlength="80" placeholder="你所在的城市"', html)
        self.assertNotIn("上海 / 北京 / 杭州", html)
        self.assertNotIn("目前上海用户优先邀请", html)
        self.assertNotIn('href="#home-title">加入内测</a>', html)

    def test_contact_phone_is_required_and_validated(self):
        beta_api = read_text("app/api/beta.py")

        self.assertIn("PHONE_PATTERN", beta_api)
        self.assertIn("contact: str = Field(...", beta_api)
        self.assertIn("请填写 11 位中国大陆手机号", beta_api)

    def test_backend_declares_public_signup_route_and_model(self):
        beta_api = ROOT / "app/api/beta.py"
        beta_model = ROOT / "app/models/beta_signup.py"
        main = read_text("app/main.py")

        self.assertTrue(beta_api.exists())
        self.assertTrue(beta_model.exists())
        self.assertIn('@router.post("/beta-signups"', beta_api.read_text(encoding="utf-8"))
        self.assertIn('__tablename__ = "beta_signups"', beta_model.read_text(encoding="utf-8"))
        self.assertIn("from app.api.beta import router as beta_router", main)
        self.assertIn("app.include_router(beta_router)", main)
        self.assertIn("from app.models.beta_signup import BetaSignup", main)

    def test_admin_can_view_and_export_beta_signups(self):
        admin_api = read_text("app/api/admin.py")
        admin_html = read_text("app/static/admin.html")

        self.assertIn("BetaSignup", admin_api)
        self.assertIn('@router.get("/beta-signups")', admin_api)
        self.assertIn('@router.get("/beta-signups.csv")', admin_api)
        self.assertIn('data-panel="beta-signups"', admin_html)
        self.assertIn('id="panel-beta-signups"', admin_html)
        self.assertIn("/api/admin/beta-signups", admin_html)
        self.assertIn("/api/admin/beta-signups.csv", admin_html)
        self.assertIn("downloadBetaSignupsCsv", admin_html)

    def test_admin_can_update_beta_signup_status_and_invite(self):
        admin_api = read_text("app/api/admin.py")
        admin_html = read_text("app/static/admin.html")

        self.assertIn('@router.patch("/beta-signups/{signup_id}/status")', admin_api)
        self.assertIn('@router.post("/beta-signups/{signup_id}/invite-internal")', admin_api)
        self.assertIn("ASC_KEY_ID", admin_api)
        self.assertIn("INTERNAL_TEST_PHONES_FILE", admin_api)
        self.assertIn("setBetaSignupStatus", admin_html)
        self.assertIn("inviteBetaSignup", admin_html)
        self.assertIn("data-beta-status", admin_html)
        self.assertIn("邀请", admin_html)


if __name__ == "__main__":
    unittest.main()
