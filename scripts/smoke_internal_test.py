#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request


BASE_URL = os.environ.get("DAZI_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PHONE = os.environ.get("DAZI_TEST_PHONE", "").strip()
CODE = os.environ.get("DAZI_TEST_CODE", "").strip()


def fail(message):
    print(f"[fail] {message}")
    sys.exit(1)


def require_env(name, value):
    if not value:
        fail(f"{name} is required")


def request_json(method, path, body=None, token=None):
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


def expect_status(label, actual, expected):
    if actual != expected:
        fail(f"{label}: expected HTTP {expected}, got HTTP {actual}")
    print(f"[ok] {label}")


def main():
    require_env("DAZI_TEST_PHONE", PHONE)
    require_env("DAZI_TEST_CODE", CODE)

    status_code, payload = request_json("GET", "/health")
    expect_status("health", status_code, 200)
    if payload != {"status": "ok"}:
        fail(f"health payload mismatch: {payload}")

    status_code, _ = request_json(
        "POST",
        "/api/v1/auth/send-code",
        {"phone": PHONE},
    )
    expect_status("send-code", status_code, 200)

    status_code, payload = request_json(
        "POST",
        "/api/v1/auth/login",
        {"phone": PHONE, "code": CODE},
    )
    expect_status("login", status_code, 200)
    token = (payload or {}).get("access_token")
    if not token:
        fail("login response missing access_token")

    status_code, payload = request_json("GET", "/api/v1/users/me", token=token)
    expect_status("users/me", status_code, 200)
    if (payload or {}).get("phone") != PHONE:
        fail(f"users/me phone mismatch: {payload}")

    print("[ok] internal test smoke finished")


if __name__ == "__main__":
    main()
