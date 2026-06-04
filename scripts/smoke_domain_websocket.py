#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

import websockets


BASE_URL = os.environ.get("DAZI_API_BASE_URL", "https://idabuda.com").rstrip("/")
WS_URL = os.environ.get("DAZI_WS_URL", "wss://idabuda.com/ws").rstrip("/")
PHONE = os.environ.get("DAZI_TEST_PHONE", "").strip()
CODE = os.environ.get("DAZI_TEST_CODE", "").strip()


def fail(message: str) -> None:
    print(f"[fail] {message}")
    sys.exit(1)


def require_env(name: str, value: str) -> None:
    if not value:
        fail(f"{name} is required")


def request_json(method: str, path: str, body: dict | None = None, token: str | None = None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else None
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload
    except urllib.error.URLError as exc:
        fail(f"cannot reach {BASE_URL}: {exc.reason}")


async def check_ws(token: str) -> None:
    async with websockets.connect(f"{WS_URL}?token={token}", open_timeout=15) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        payload = json.loads(raw)
        if payload != {"type": "pong"}:
            fail(f"unexpected websocket payload: {payload}")
        print("[ok] websocket ping/pong")


def main() -> None:
    require_env("DAZI_TEST_PHONE", PHONE)
    require_env("DAZI_TEST_CODE", CODE)

    status_code, _ = request_json("POST", "/api/v1/auth/send-code", {"phone": PHONE})
    if status_code != 200:
        fail(f"send-code expected HTTP 200, got HTTP {status_code}")

    status_code, payload = request_json("POST", "/api/v1/auth/login", {"phone": PHONE, "code": CODE})
    if status_code != 200:
        fail(f"login expected HTTP 200, got HTTP {status_code}: {payload}")

    token = (payload or {}).get("access_token")
    if not token:
        fail("login response missing access_token")

    asyncio.run(check_ws(token))
    print("[ok] domain websocket smoke finished")


if __name__ == "__main__":
    main()
