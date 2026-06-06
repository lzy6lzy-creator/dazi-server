from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ChatPushStaticTests(unittest.TestCase):
    def test_push_notification_failure_does_not_abort_user_message_send(self):
        text = (ROOT / "app" / "api" / "chat.py").read_text(encoding="utf-8")

        send_message_body = text.split("async def send_message", 1)[1].split(
            '@router.post("/rooms/{room_id}/close")',
            1,
        )[0]

        self.assertIn("await _push_message_to_room(room_id, msg, db, exclude_user_ids={user_id})", send_message_body)
        self.assertIn("try:", send_message_body)
        self.assertIn("except Exception", send_message_body)
        self.assertIn("logger.warning", send_message_body)


if __name__ == "__main__":
    unittest.main()
