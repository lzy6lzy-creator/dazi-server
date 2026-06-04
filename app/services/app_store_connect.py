from __future__ import annotations

import time
from pathlib import Path

import httpx
from jose import jwt


class AppStoreConnectError(Exception):
    """Raised when App Store Connect returns an unexpected response."""


class AppStoreConnectConfigError(AppStoreConnectError):
    """Raised when App Store Connect API credentials are incomplete."""


def split_name(name: str) -> tuple[str, str]:
    cleaned = (name or "").strip()
    if not cleaned:
        return "Beta", "Tester"
    parts = cleaned.split(maxsplit=1)
    if len(parts) == 2:
        return parts[0][:40], parts[1][:40]
    return cleaned[:40], "Tester"


class AppStoreConnectClient:
    base_url = "https://api.appstoreconnect.apple.com"

    def __init__(
        self,
        *,
        key_id: str,
        issuer_id: str,
        private_key_path: str,
        bundle_id: str,
        app_id: str = "",
        internal_group_name: str = "",
        internal_group_id: str = "",
        invite_role: str = "MARKETING",
    ):
        self.key_id = key_id.strip()
        self.issuer_id = issuer_id.strip()
        self.private_key_path = private_key_path.strip()
        self.bundle_id = bundle_id.strip()
        self.app_id = app_id.strip()
        self.internal_group_name = internal_group_name.strip()
        self.internal_group_id = internal_group_id.strip()
        self.invite_role = (invite_role or "MARKETING").strip().upper()
        self._private_key: str | None = None

        missing = [
            name
            for name, value in [
                ("ASC_KEY_ID", self.key_id),
                ("ASC_ISSUER_ID", self.issuer_id),
                ("ASC_PRIVATE_KEY_PATH", self.private_key_path),
                ("ASC_BUNDLE_ID", self.bundle_id),
            ]
            if not value
        ]
        if missing:
            raise AppStoreConnectConfigError(f"缺少 App Store Connect 配置: {', '.join(missing)}")
        if not self.internal_group_id and not self.internal_group_name:
            raise AppStoreConnectConfigError("缺少 ASC_INTERNAL_GROUP_ID 或 ASC_INTERNAL_GROUP_NAME")

    @classmethod
    def from_settings(cls, settings):
        return cls(
            key_id=settings.ASC_KEY_ID,
            issuer_id=settings.ASC_ISSUER_ID,
            private_key_path=settings.ASC_PRIVATE_KEY_PATH,
            bundle_id=settings.ASC_BUNDLE_ID,
            app_id=settings.ASC_APP_ID,
            internal_group_name=settings.ASC_INTERNAL_GROUP_NAME,
            internal_group_id=settings.ASC_INTERNAL_GROUP_ID,
            invite_role=settings.ASC_INVITE_ROLE,
        )

    def _load_private_key(self) -> str:
        if self._private_key is None:
            path = Path(self.private_key_path)
            if not path.exists():
                raise AppStoreConnectConfigError(f"ASC_PRIVATE_KEY_PATH 不存在: {path}")
            self._private_key = path.read_text(encoding="utf-8")
        return self._private_key

    def _token(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self.issuer_id,
            "iat": now,
            "exp": now + 20 * 60,
            "aud": "appstoreconnect-v1",
        }
        headers = {"alg": "ES256", "kid": self.key_id, "typ": "JWT"}
        return jwt.encode(payload, self._load_private_key(), algorithm="ES256", headers=headers)

    async def _request(self, method: str, path: str, *, params=None, json_body=None, expected=(200,)):
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            response = await client.request(method, path, params=params, json=json_body, headers=headers)
        if response.status_code not in expected:
            raise AppStoreConnectError(self._error_message(response))
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return f"App Store Connect HTTP {response.status_code}: {response.text[:300]}"
        errors = data.get("errors") or []
        if not errors:
            return f"App Store Connect HTTP {response.status_code}"
        first = errors[0]
        title = first.get("title") or "request failed"
        detail = first.get("detail") or first.get("code") or ""
        return f"App Store Connect HTTP {response.status_code}: {title}. {detail}".strip()

    async def get_app_id(self) -> str:
        if self.app_id:
            return self.app_id
        data = await self._request("GET", "/v1/apps", params={"filter[bundleId]": self.bundle_id})
        apps = data.get("data") or []
        if not apps:
            raise AppStoreConnectError(f"找不到 bundle id 对应的 App: {self.bundle_id}")
        self.app_id = apps[0]["id"]
        return self.app_id

    async def get_internal_group_id(self, app_id: str) -> str:
        if self.internal_group_id:
            return self.internal_group_id
        data = await self._request(
            "GET",
            "/v1/betaGroups",
            params={
                "filter[app]": app_id,
                "filter[name]": self.internal_group_name,
                "filter[isInternalGroup]": "true",
                "fields[betaGroups]": "name,isInternalGroup",
                "limit": "10",
            },
        )
        groups = data.get("data") or []
        if not groups:
            raise AppStoreConnectError(f"找不到内部测试组: {self.internal_group_name}")
        self.internal_group_id = groups[0]["id"]
        return self.internal_group_id

    async def get_user(self, email: str):
        data = await self._request(
            "GET",
            "/v1/users",
            params={"filter[username]": email, "fields[users]": "username,roles", "limit": "10"},
        )
        rows = data.get("data") or []
        return rows[0] if rows else None

    async def get_pending_invitation(self, email: str):
        data = await self._request(
            "GET",
            "/v1/userInvitations",
            params={"filter[email]": email, "fields[userInvitations]": "email,expirationDate,roles", "limit": "10"},
        )
        rows = data.get("data") or []
        return rows[0] if rows else None

    async def create_user_invitation(self, *, email: str, name: str, app_id: str):
        first_name, last_name = split_name(name)
        body = {
            "data": {
                "type": "userInvitations",
                "attributes": {
                    "email": email,
                    "firstName": first_name,
                    "lastName": last_name,
                    "roles": [self.invite_role],
                    "allAppsVisible": False,
                    "provisioningAllowed": False,
                },
                "relationships": {
                    "visibleApps": {
                        "data": [{"type": "apps", "id": app_id}],
                    },
                },
            },
        }
        return await self._request("POST", "/v1/userInvitations", json_body=body, expected=(201,))

    async def get_beta_tester(self, email: str):
        data = await self._request(
            "GET",
            "/v1/betaTesters",
            params={"filter[email]": email, "fields[betaTesters]": "email,state,inviteType", "limit": "10"},
        )
        rows = data.get("data") or []
        return rows[0] if rows else None

    async def create_beta_tester(self, *, email: str, name: str, group_id: str):
        first_name, last_name = split_name(name)
        body = {
            "data": {
                "type": "betaTesters",
                "attributes": {
                    "email": email,
                    "firstName": first_name,
                    "lastName": last_name,
                },
                "relationships": {
                    "betaGroups": {
                        "data": [{"type": "betaGroups", "id": group_id}],
                    },
                },
            },
        }
        return await self._request("POST", "/v1/betaTesters", json_body=body, expected=(201,))

    async def add_beta_tester_to_group(self, *, beta_tester_id: str, group_id: str):
        body = {"data": [{"type": "betaGroups", "id": group_id}]}
        return await self._request(
            "POST",
            f"/v1/betaTesters/{beta_tester_id}/relationships/betaGroups",
            json_body=body,
            expected=(204, 409),
        )

    async def invite_internal_tester(self, *, email: str, name: str) -> dict:
        app_id = await self.get_app_id()
        group_id = await self.get_internal_group_id(app_id)

        user = await self.get_user(email)
        pending = None
        invitation = None
        invitation_status = "accepted"
        if not user:
            pending = await self.get_pending_invitation(email)
            if pending:
                invitation_status = "pending_existing"
            else:
                invitation = await self.create_user_invitation(email=email, name=name, app_id=app_id)
                invitation_status = "created"

        beta_tester_status = "waiting_for_user_acceptance"
        beta_tester_id = None
        if user:
            beta_tester = await self.get_beta_tester(email)
            if beta_tester:
                beta_tester_id = beta_tester["id"]
                await self.add_beta_tester_to_group(beta_tester_id=beta_tester_id, group_id=group_id)
                beta_tester_status = "group_attached"
            else:
                created = await self.create_beta_tester(email=email, name=name, group_id=group_id)
                beta_tester_id = created["data"]["id"]
                beta_tester_status = "created"

        return {
            "app_id": app_id,
            "group_id": group_id,
            "user_id": user["id"] if user else None,
            "user_invitation_status": invitation_status,
            "user_invitation_id": (
                invitation["data"]["id"] if invitation else pending["id"] if pending else None
            ),
            "beta_tester_status": beta_tester_status,
            "beta_tester_id": beta_tester_id,
        }
