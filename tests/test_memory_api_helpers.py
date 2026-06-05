from __future__ import annotations

import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.api.schemas import MemoryUpdate
from app.models.user import AgentMemory


class MemoryApiHelperTests(unittest.TestCase):
    def test_memory_model_exposes_long_term_fields(self):
        memory = AgentMemory(
            user_id=uuid4(),
            type="style",
            content="喜欢直接总结后确认",
            key="style.confirmation",
            category="style",
            occurrence_count=2,
            status="active",
        )

        self.assertEqual(memory.key, "style.confirmation")
        self.assertEqual(memory.category, "style")
        self.assertEqual(memory.occurrence_count, 2)
        self.assertEqual(memory.status, "active")

    def test_memory_update_requires_content_or_active_change(self):
        with self.assertRaises(ValidationError):
            MemoryUpdate()

        valid = MemoryUpdate(content="不吃辣")
        self.assertEqual(valid.content, "不吃辣")


if __name__ == "__main__":
    unittest.main()
