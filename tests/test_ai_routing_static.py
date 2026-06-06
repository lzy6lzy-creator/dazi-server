from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AIRoutingStaticTests(unittest.TestCase):
    def test_all_ai_calls_route_through_agent_server(self):
        offenders = []
        for path in (ROOT / "app").rglob("*.py"):
            if path.name == "llm_service.py":
                offenders.append(str(path.relative_to(ROOT)))
                continue
            text = path.read_text(encoding="utf-8")
            if "app.services.llm_service" in text or "llm_service" in text:
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_legacy_llm_service_module_is_removed(self):
        self.assertFalse((ROOT / "app" / "services" / "llm_service.py").exists())


if __name__ == "__main__":
    unittest.main()
