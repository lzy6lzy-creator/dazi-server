#!/usr/bin/env python3
import argparse
import secrets
from pathlib import Path


DEFAULT_ENV_PATH = Path(".env")


def parse_env(lines):
    values = {}
    order = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
        order.append(key)
    return values, order


def six_digit_code():
    return f"{secrets.randbelow(900000) + 100000}"


def set_default(values, order, key, value):
    if values.get(key):
        return "existing"
    values[key] = value
    if key not in order:
        order.append(key)
    return "created"


def render_env(values, order, original_lines):
    seen = set()
    rendered = []
    for line in original_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rendered.append(line.rstrip("\n"))
            continue

        key, _ = stripped.split("=", 1)
        if key in values:
            rendered.append(f"{key}={values[key]}")
            seen.add(key)

    for key in order:
        if key not in seen:
            rendered.append(f"{key}={values[key]}")
            seen.add(key)

    return "\n".join(rendered).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--phone", default="13800001111")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    original_lines = env_path.read_text().splitlines() if env_path.exists() else []
    values, order = parse_env(original_lines)

    results = {
        "ADMIN_TOKEN": set_default(values, order, "ADMIN_TOKEN", secrets.token_urlsafe(32)),
        "INTERNAL_TEST_MODE": set_default(values, order, "INTERNAL_TEST_MODE", "true"),
        "INTERNAL_TEST_CODE": set_default(values, order, "INTERNAL_TEST_CODE", six_digit_code()),
        "INTERNAL_TEST_PHONES": set_default(values, order, "INTERNAL_TEST_PHONES", args.phone),
    }

    env_path.write_text(render_env(values, order, original_lines))
    for key, result in results.items():
        print(f"{key}={result}")


if __name__ == "__main__":
    main()
