import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.api.chat_helpers import room_event_ids


class ChatHelperTests(unittest.TestCase):
    def test_room_event_ids_returns_both_sides(self):
        event_a_id = uuid4()
        event_b_id = uuid4()
        room = SimpleNamespace(event_id_a=event_a_id, event_id_b=event_b_id)

        self.assertEqual(room_event_ids(room), [event_a_id, event_b_id])

    def test_room_event_ids_ignores_missing_side(self):
        event_a_id = uuid4()
        room = SimpleNamespace(event_id_a=event_a_id, event_id_b=None)

        self.assertEqual(room_event_ids(room), [event_a_id])


if __name__ == "__main__":
    unittest.main()
