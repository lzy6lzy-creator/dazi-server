from __future__ import annotations

import unittest
from pathlib import Path

from app.api.schemas import PushDeviceTokenRequest
from app.services.push_notification_service import (
    PushNotificationService,
    apns_base_url_for_environment,
    build_apns_payload,
)


ROOT = Path(__file__).resolve().parents[1]


class PushNotificationTests(unittest.TestCase):
    def test_build_apns_payload_includes_alert_sound_badge_and_room_data(self):
        payload = build_apns_payload(
            title="匹配成功，聊天室已创建",
            body="「周末电影」的搭子聊天室已开启",
            data={"type": "room_created", "room_id": "room-1"},
            badge=2,
        )

        self.assertEqual(
            payload["aps"]["alert"],
            {"title": "匹配成功，聊天室已创建", "body": "「周末电影」的搭子聊天室已开启"},
        )
        self.assertEqual(payload["aps"]["sound"], "default")
        self.assertEqual(payload["aps"]["badge"], 2)
        self.assertEqual(payload["type"], "room_created")
        self.assertEqual(payload["room_id"], "room-1")

    def test_apns_environment_selects_correct_gateway(self):
        self.assertEqual(
            apns_base_url_for_environment("production"),
            "https://api.push.apple.com",
        )
        self.assertEqual(
            apns_base_url_for_environment("sandbox"),
            "https://api.sandbox.push.apple.com",
        )

    def test_service_reports_unconfigured_without_credentials(self):
        service = PushNotificationService(
            key_id="",
            team_id="",
            private_key_path="",
            bundle_id="com.linke.dazi",
        )

        self.assertFalse(service.is_configured)

    def test_device_token_request_normalizes_platform_and_environment(self):
        request = PushDeviceTokenRequest(
            token="  ABCDEF  ",
            platform=" IOS ",
            environment=" PRODUCTION ",
        )

        self.assertEqual(request.token, "ABCDEF")
        self.assertEqual(request.platform, "ios")
        self.assertEqual(request.environment, "production")

    def test_chat_room_creation_invokes_remote_push(self):
        text = (ROOT / "app" / "services" / "matching_service.py").read_text(encoding="utf-8")

        create_room_body = text.split("async def _create_chat_room", 1)[1]
        self.assertIn("push_notification_service.send_to_users", create_room_body)
        self.assertIn('"type": "room_created"', create_room_body)

    def test_user_chat_messages_push_to_room_members_except_sender(self):
        text = (ROOT / "app" / "api" / "chat.py").read_text(encoding="utf-8")

        send_message_body = text.split("async def send_message", 1)[1]
        self.assertIn("await _push_message_to_room", send_message_body)
        self.assertIn("exclude_user_ids={user_id}", send_message_body)


if __name__ == "__main__":
    unittest.main()
