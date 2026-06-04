#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


BASE_URL = os.environ.get("DAZI_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PHONES_FILE = Path(os.environ.get("DAZI_INTERNAL_PHONES_FILE", "internal_test_phones.txt"))
TEMP_PHONE = os.environ.get("DAZI_HOT_RELOAD_PHONE", "16600009999").strip()
CONTAINER_NAME = os.environ.get("DAZI_CONTAINER_NAME", "dazi-api").strip()


def fail(message):
    print(f"[fail] {message}")
    sys.exit(1)


def container_state():
    if not CONTAINER_NAME:
        return ""
    try:
        return subprocess.check_output(
            ["docker", "inspect", CONTAINER_NAME],
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""


def send_code_status(phone):
    req = urllib.request.Request(
        f"{BASE_URL}/api/v1/auth/send-code",
        data=json.dumps({"phone": phone}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code
    except urllib.error.URLError as exc:
        fail(f"cannot reach {BASE_URL}: {exc.reason}")


def without_temp_phone(raw):
    return "\n".join(line for line in raw.splitlines() if TEMP_PHONE not in line).rstrip() + "\n"


def main():
    if not TEMP_PHONE:
        fail("DAZI_HOT_RELOAD_PHONE is required")
    if not PHONES_FILE.exists():
        fail(f"phones file not found: {PHONES_FILE}")

    original = PHONES_FILE.read_text(encoding="utf-8")
    before_container = container_state()

    try:
        PHONES_FILE.write_text(without_temp_phone(original), encoding="utf-8")
        before = send_code_status(TEMP_PHONE)

        PHONES_FILE.write_text(
            PHONES_FILE.read_text(encoding="utf-8").rstrip() + f"\n{TEMP_PHONE}\n",
            encoding="utf-8",
        )
        after_add = send_code_status(TEMP_PHONE)

        PHONES_FILE.write_text(original, encoding="utf-8")
        after_restore = send_code_status(TEMP_PHONE)
    finally:
        PHONES_FILE.write_text(original, encoding="utf-8")

    after_container = container_state()
    if before_container and after_container and before_container != after_container:
        fail("container changed while testing whitelist hot reload")
    if before == 200:
        fail(f"{TEMP_PHONE} was allowed before file update")
    if after_add != 200:
        fail(f"{TEMP_PHONE} was not allowed after file update: HTTP {after_add}")
    if after_restore == 200:
        fail(f"{TEMP_PHONE} remained allowed after restoring file")

    print(f"[ok] before update HTTP {before}")
    print("[ok] after file update HTTP 200")
    print(f"[ok] after restore HTTP {after_restore}")
    if before_container:
        print("[ok] container did not restart")
    print("[ok] internal phone whitelist hot reload finished")


if __name__ == "__main__":
    main()
