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


if __name__ == "__main__":
    unittest.main()
