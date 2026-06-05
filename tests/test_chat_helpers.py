import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.api.chat import _chat_room_member_response
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

    def test_chat_room_member_response_includes_user_avatar(self):
        user_id = uuid4()
        member = SimpleNamespace(user_id=user_id, role="user")
        user = SimpleNamespace(name="阿树", avatar_url="🙂")

        response = _chat_room_member_response(member, user=user)

        self.assertEqual(response.user_id, user_id)
        self.assertEqual(response.role, "user")
        self.assertEqual(response.emoji, "🙂")
        self.assertEqual(response.avatar_url, "🙂")

    def test_chat_room_member_response_includes_agent_avatar(self):
        user_id = uuid4()
        member = SimpleNamespace(user_id=user_id, role="agent")
        agent = SimpleNamespace(name="点点", emoji="✨", avatar_url="agent-image")

        response = _chat_room_member_response(member, agent=agent)

        self.assertEqual(response.user_id, user_id)
        self.assertEqual(response.role, "agent")
        self.assertEqual(response.emoji, "✨")
        self.assertEqual(response.avatar_url, "agent-image")


if __name__ == "__main__":
    unittest.main()
