from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HomepageStaticTests(unittest.TestCase):
    def homepage(self) -> str:
        return (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    def test_homepage_is_user_facing_and_clean(self):
        html = self.homepage()

        self.assertIn("想做的事，终于有人一起。", html)
        self.assertIn("告诉你的 AI 经纪人", html)
        self.assertIn("加入内测", html)
        self.assertIn("hero-activity-cards.png", html)
        self.assertNotIn("技术栈", html)
        self.assertNotIn("A2A 匹配架构", html)
        self.assertNotIn("SwiftUI", html)
        self.assertNotIn("PostgreSQL + pgvector", html)

    def test_homepage_uses_lowercase_i_branding(self):
        html = self.homepage()

        self.assertIn("i搭不搭", html)
        self.assertNotIn("I搭不搭", html)

    def test_static_website_pages_use_lowercase_i_branding(self):
        html_files = list((ROOT / "app/static").glob("*.html")) + [ROOT / "site/index.html"]

        for path in html_files:
            with self.subTest(path=path.relative_to(ROOT)):
                html = path.read_text(encoding="utf-8")
                self.assertNotIn("I搭不搭", html)

    def test_fastapi_public_title_uses_lowercase_i_branding(self):
        source = (ROOT / "app/main.py").read_text(encoding="utf-8")

        self.assertIn('title="i搭不搭 API"', source)
        self.assertNotIn('title="I搭不搭 API"', source)

    def test_homepage_explains_ai_matching_without_technical_jargon(self):
        html = self.homepage()

        self.assertIn("双方 AI 先聊一轮", html)
        self.assertIn("时间合得上", html)
        self.assertIn("地点不折腾", html)
        self.assertIn("活动偏好接近", html)
        self.assertNotIn("Agent-to-Agent", html)

    def test_homepage_hides_internal_utility_links(self):
        html = self.homepage()

        self.assertNotIn("API 文档", html)
        self.assertNotIn("管理后台", html)
        self.assertNotRegex(html, r'<a[^>]+href="/docs"')
        self.assertNotRegex(html, r'<a[^>]+href="/admin"')

    def test_hero_asset_exists_and_no_emoji_icon_copy(self):
        html = self.homepage()
        asset = ROOT / "app/static/assets/hero-activity-cards.png"

        self.assertTrue(asset.exists())
        self.assertLess(asset.stat().st_size, 2_500_000)
        for emoji in ["✨", "🤖", "💬", "🔒", "😫", "😰", "🎯"]:
            self.assertNotIn(emoji, html)

    def test_text_fits_static_page_without_viewport_font_scaling(self):
        html = self.homepage()

        self.assertNotRegex(html, re.compile(r"font-size\s*:\s*[^;]*(vw|vh)", re.I))
        self.assertIn("@media (max-width: 760px)", html)


if __name__ == "__main__":
    unittest.main()
