from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.api.chat import _extract_room_agent_reply, _format_room_event_context
from app.models.event import Event


class RoomAgentHelperTests(unittest.TestCase):
    def test_format_room_event_context_marks_self_and_preserves_null_fields(self):
        user_id = uuid4()
        event = Event(
            user_id=user_id,
            title="周末咖啡",
            activity_type="咖啡",
            city="上海",
            location=None,
            start_time=None,
            end_time=datetime(2026, 6, 6, 16, 0, tzinfo=timezone.utc),
            preferences=["安静一点"],
            constraints=[],
        )

        text = _format_room_event_context(event, "B", user_id)

        self.assertIn("B（你这边）", text)
        self.assertIn("location=null", text)
        self.assertIn("start_time=null", text)
        self.assertIn("preferences=安静一点", text)

    def test_extract_room_agent_reply_prefers_json_reply(self):
        raw = '{"reply":"不能直接定，需要你本人先确认。","needs_user_confirmation":true}'

        self.assertEqual(_extract_room_agent_reply(raw), "不能直接定，需要你本人先确认。")

    def test_extract_room_agent_reply_falls_back_to_raw_text(self):
        self.assertEqual(_extract_room_agent_reply("直接确认具体球场即可。"), "直接确认具体球场即可。")


if __name__ == "__main__":
    unittest.main()
