from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MatchingTasksStaticTests(unittest.TestCase):
    def test_direct_event_creation_schedules_immediate_matching(self):
        text = (ROOT / "app" / "api" / "events.py").read_text(encoding="utf-8")

        self.assertIn("schedule_event_matching(background_tasks, event.id)", text)

    def test_agent_event_creation_schedules_immediate_matching(self):
        text = (ROOT / "app" / "api" / "agent_chat.py").read_text(encoding="utf-8")

        self.assertIn("schedule_event_matching(background_tasks, event_id)", text)

    def test_matching_task_uses_fresh_session(self):
        text = (ROOT / "app" / "services" / "matching_tasks.py").read_text(encoding="utf-8")

        self.assertIn("async with async_session() as db", text)
        self.assertIn("matching_service.match_event(event_id, db)", text)


if __name__ == "__main__":
    unittest.main()
