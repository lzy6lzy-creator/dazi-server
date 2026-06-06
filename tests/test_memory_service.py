from __future__ import annotations

import unittest
from uuid import uuid4

from app.models.user import AgentMemory
from app.services.memory_service import (
    build_event_memory_candidates,
    derive_long_term_memory_actions,
    format_memory_context,
    memory_updated_payload,
)


class MemoryServiceTests(unittest.TestCase):
    def test_event_draft_preferences_create_event_memory_candidates(self):
        user_id = uuid4()
        event_id = uuid4()
        candidates = build_event_memory_candidates(
            user_id=user_id,
            event_id=event_id,
            draft={
                "activity_type": "网球",
                "city": "上海",
                "location": "徐汇",
                "preferences": ["新手也行", "场地费 AA"],
                "constraints": [],
            },
        )

        contents = [item.content for item in candidates]
        self.assertIn("新手也行", contents)
        self.assertIn("场地费 AA", contents)
        self.assertTrue(all(item.event_id == event_id for item in candidates))

    def test_temporary_event_text_is_ignored_for_long_term_memory(self):
        actions = derive_long_term_memory_actions(
            text="今晚想吃火锅，预算 50-80",
            event_memories=[],
            existing_memories=[],
        )

        self.assertTrue(actions)
        self.assertTrue(all(action.action == "ignore" for action in actions))

    def test_explicit_constraint_creates_long_term_memory(self):
        actions = derive_long_term_memory_actions(
            text="我不能吃辣",
            event_memories=[],
            existing_memories=[],
        )

        create = [action for action in actions if action.action == "create"]
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0].type, "constraint")
        self.assertEqual(create[0].category, "food")
        self.assertEqual(create[0].content, "不能吃辣")

    def test_repeated_event_candidate_weakly_upgrades(self):
        existing = AgentMemory(
            user_id=uuid4(),
            type="preference",
            content="偏好场地费 AA",
            key="budget.cost_share",
            category="budget",
            occurrence_count=1,
            confidence=0.45,
        )
        event_memories = build_event_memory_candidates(
            user_id=existing.user_id,
            event_id=uuid4(),
            draft={"preferences": ["场地费 AA"]},
        )

        actions = derive_long_term_memory_actions(
            text="这次继续场地费 AA",
            event_memories=event_memories,
            existing_memories=[existing],
        )

        reinforce = [action for action in actions if action.action == "reinforce"]
        self.assertEqual(len(reinforce), 1)
        self.assertEqual(reinforce[0].target_memory_id, existing.id)

    def test_activity_type_event_memory_uses_stable_key(self):
        user_id = uuid4()
        first = build_event_memory_candidates(
            user_id=user_id,
            event_id=uuid4(),
            draft={"activity_type": "火锅"},
        )
        second = build_event_memory_candidates(
            user_id=user_id,
            event_id=uuid4(),
            draft={"activity_type": "火锅"},
        )

        self.assertEqual(first[0].key, "event.activity_type.火锅")
        self.assertEqual(first[0].key, second[0].key)

    def test_repeated_activity_type_reinforces_single_memory(self):
        user_id = uuid4()
        existing = AgentMemory(
            user_id=user_id,
            type="preference",
            content="经常发起火锅活动",
            key="event.activity_type.火锅",
            category="activity",
            occurrence_count=2,
            confidence=0.55,
        )
        event_memories = build_event_memory_candidates(
            user_id=user_id,
            event_id=uuid4(),
            draft={"activity_type": "火锅"},
        )

        actions = derive_long_term_memory_actions(
            text="周末继续吃火锅",
            event_memories=event_memories,
            existing_memories=[existing],
        )

        reinforce = [action for action in actions if action.action == "reinforce"]
        self.assertEqual(len(reinforce), 1)
        self.assertEqual(reinforce[0].target_memory_id, existing.id)
        self.assertEqual(reinforce[0].key, "event.activity_type.火锅")

    def test_style_memory_context_is_supported(self):
        memory = AgentMemory(
            user_id=uuid4(),
            type="style",
            content="喜欢直接总结后确认",
            category="style",
            confidence=0.68,
        )

        text = format_memory_context([memory])

        self.assertIn("[风格][style]", text)
        self.assertIn("喜欢直接总结后确认", text)

    def test_memory_updated_payload_includes_app_toast_fields(self):
        memory = AgentMemory(
            id=uuid4(),
            user_id=uuid4(),
            type="preference",
            content="经常发起火锅活动",
            key="event.activity_type.火锅",
            category="activity",
            occurrence_count=3,
            confidence=0.71,
            status="active",
        )

        payload = memory_updated_payload(memory, action="reinforce")

        self.assertEqual(payload["type"], "memory_updated")
        self.assertEqual(payload["action"], "reinforce")
        self.assertEqual(payload["memory"]["id"], str(memory.id))
        self.assertEqual(payload["memory"]["content"], "经常发起火锅活动")
        self.assertEqual(payload["memory"]["occurrence_count"], 3)


if __name__ == "__main__":
    unittest.main()
