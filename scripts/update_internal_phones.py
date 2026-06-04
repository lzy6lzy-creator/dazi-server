#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

from prepare_internal_env import parse_env, render_env, six_digit_code


PHONE_RE = re.compile(r"^\+?\d{6,20}$")


def read_phones(path):
    phones = []
    seen = set()
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        raw = line.split("#", 1)[0].strip()
        if not raw:
            continue

        for item in raw.split(","):
            phone = item.strip().replace(" ", "").replace("-", "")
            if not phone:
                continue
            if not PHONE_RE.fullmatch(phone):
                raise ValueError(f"{path}:{line_no} invalid phone: {item.strip()}")
            if phone not in seen:
                phones.append(phone)
                seen.add(phone)

    if not phones:
        raise ValueError(f"{path} must contain at least one phone number")
    return phones


def ensure_key(order, key):
    if key not in order:
        order.append(key)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phones-file", default="internal_test_phones.txt")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    phones_path = Path(args.phones_file)
    env_path = Path(args.env_file)

    phones = read_phones(phones_path)
    original_lines = env_path.read_text().splitlines() if env_path.exists() else []
    values, order = parse_env(original_lines)

    values["INTERNAL_TEST_MODE"] = "true"
    values["INTERNAL_TEST_PHONES"] = ",".join(phones)
    if not values.get("INTERNAL_TEST_CODE"):
        values["INTERNAL_TEST_CODE"] = six_digit_code()

    ensure_key(order, "INTERNAL_TEST_MODE")
    ensure_key(order, "INTERNAL_TEST_CODE")
    ensure_key(order, "INTERNAL_TEST_PHONES")

    env_path.write_text(render_env(values, order, original_lines))
    print(f"INTERNAL_TEST_PHONES=updated:{len(phones)}")
    print("INTERNAL_TEST_MODE=true")
    print("INTERNAL_TEST_CODE=kept" if values.get("INTERNAL_TEST_CODE") else "INTERNAL_TEST_CODE=created")


if __name__ == "__main__":
    main()
