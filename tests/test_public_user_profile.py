from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas import PublicUserProfileResponse


class PublicUserProfileTests(unittest.TestCase):
    def test_public_profile_response_exposes_partner_safe_fields(self):
        user_id = uuid4()
        user = SimpleNamespace(
            id=user_id,
            name="阿树",
            phone="13800000000",
            gender="暂时保密",
            birth_year=1998,
            birth_date=None,
            bio="喜欢周末看展",
            avatar_url="https://example.com/avatar.png",
            interests=["看展", "咖啡"],
            city="上海",
            occupation="设计师",
            custom_interests="爵士现场",
            welcome_disturb=True,
        )

        response = PublicUserProfileResponse.model_validate(user)
        payload = response.model_dump()

        self.assertEqual(payload["id"], user_id)
        self.assertEqual(payload["name"], "阿树")
        self.assertEqual(payload["interests"], ["看展", "咖啡"])
        self.assertEqual(payload["city"], "上海")
        self.assertEqual(payload["occupation"], "设计师")
        self.assertEqual(payload["welcome_disturb"], True)
        self.assertNotIn("phone", payload)


if __name__ == "__main__":
    unittest.main()
