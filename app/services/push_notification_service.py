from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import PushDeviceToken

logger = logging.getLogger(__name__)

APNS_PRODUCTION_URL = "https://api.push.apple.com"
APNS_SANDBOX_URL = "https://api.sandbox.push.apple.com"
DEACTIVATE_REASONS = {"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"}


@dataclass(frozen=True)
class PushSendResult:
    token: str
    success: bool
    status_code: int | None = None
    reason: str = ""
    should_deactivate: bool = False


def apns_base_url_for_environment(environment: str) -> str:
    return APNS_SANDBOX_URL if (environment or "").strip().lower() == "sandbox" else APNS_PRODUCTION_URL


def build_apns_payload(
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    badge: int | None = None,
) -> dict[str, Any]:
    aps: dict[str, Any] = {
        "alert": {
            "title": title,
            "body": body,
        },
        "sound": "default",
    }
    if badge is not None:
        aps["badge"] = max(0, badge)

    payload: dict[str, Any] = {"aps": aps}
    for key, value in (data or {}).items():
        if key == "aps" or value is None:
            continue
        payload[key] = value
    return payload


class PushNotificationService:
    def __init__(
        self,
        *,
        key_id: str,
        team_id: str,
        private_key_path: str,
        bundle_id: str,
    ):
        self.key_id = (key_id or "").strip()
        self.team_id = (team_id or "").strip()
        self.private_key_path = (private_key_path or "").strip()
        self.bundle_id = (bundle_id or "").strip()
        self._private_key: str | None = None
        self._provider_token: str | None = None
        self._provider_token_iat: int = 0

    @classmethod
    def from_settings(cls, config) -> "PushNotificationService":
        return cls(
            key_id=config.APNS_KEY_ID,
            team_id=config.APNS_TEAM_ID,
            private_key_path=config.APNS_PRIVATE_KEY_PATH,
            bundle_id=config.APNS_BUNDLE_ID or config.ASC_BUNDLE_ID,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.key_id and self.team_id and self.private_key_path and self.bundle_id)

    async def send_to_users(
        self,
        db: AsyncSession,
        user_ids: Iterable[UUID],
        *,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        badge: int | None = None,
    ) -> list[PushSendResult]:
        if not self.is_configured:
            logger.info("APNs push skipped because APNS_* credentials are not configured.")
            return []

        unique_user_ids = list(dict.fromkeys(user_ids))
        if not unique_user_ids:
            return []

        result = await db.execute(
            select(PushDeviceToken).where(
                PushDeviceToken.user_id.in_(unique_user_ids),
                PushDeviceToken.platform == "ios",
                PushDeviceToken.is_active == True,
            )
        )
        rows = result.scalars().all()
        if not rows:
            return []

        payload = build_apns_payload(title=title, body=body, data=data, badge=badge)
        send_results: list[PushSendResult] = []
        for row in rows:
            send_result = await self.send_to_token(
                token=row.token,
                environment=row.environment,
                payload=payload,
            )
            send_results.append(send_result)
            if send_result.should_deactivate:
                row.is_active = False
                row.updated_at = datetime.now(timezone.utc)
        return send_results

    async def send_to_token(
        self,
        *,
        token: str,
        environment: str,
        payload: dict[str, Any],
    ) -> PushSendResult:
        if not self.is_configured:
            return PushSendResult(token=token, success=False, reason="not_configured")

        url = f"/3/device/{token}"
        headers = {
            "authorization": f"bearer {self._provider_auth_token()}",
            "apns-topic": self.bundle_id,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }

        try:
            async with httpx.AsyncClient(
                base_url=apns_base_url_for_environment(environment),
                http2=True,
                timeout=10.0,
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except Exception as exc:
            logger.warning("APNs push request failed: %s", exc)
            return PushSendResult(token=token, success=False, reason=str(exc))

        if response.status_code == 200:
            return PushSendResult(token=token, success=True, status_code=response.status_code)

        reason = self._response_reason(response)
        should_deactivate = response.status_code == 410 or reason in DEACTIVATE_REASONS
        logger.warning("APNs push failed: status=%s reason=%s", response.status_code, reason)
        return PushSendResult(
            token=token,
            success=False,
            status_code=response.status_code,
            reason=reason,
            should_deactivate=should_deactivate,
        )

    def _provider_auth_token(self) -> str:
        now = int(time.time())
        if self._provider_token and now - self._provider_token_iat < 50 * 60:
            return self._provider_token

        headers = {"alg": "ES256", "kid": self.key_id}
        payload = {"iss": self.team_id, "iat": now}
        self._provider_token = jwt.encode(
            payload,
            self._load_private_key(),
            algorithm="ES256",
            headers=headers,
        )
        self._provider_token_iat = now
        return self._provider_token

    def _load_private_key(self) -> str:
        if self._private_key is None:
            path = Path(self.private_key_path)
            if not path.exists():
                raise FileNotFoundError(f"APNS_PRIVATE_KEY_PATH does not exist: {path}")
            self._private_key = path.read_text(encoding="utf-8")
        return self._private_key

    @staticmethod
    def _response_reason(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text[:200]
        reason = data.get("reason")
        return str(reason or "unknown")


push_notification_service = PushNotificationService.from_settings(settings)
