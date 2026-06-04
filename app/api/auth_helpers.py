import re
from pathlib import Path
from typing import Optional, Set


PHONE_RE = re.compile(r"^\+?\d{6,20}$")


def _normalize_phone(raw: str) -> str:
    return raw.strip().replace(" ", "").replace("-", "")


def _phone_values(raw: Optional[str]) -> Set[str]:
    if not raw:
        return set()

    phones = set()
    for item in raw.split(","):
        phone = _normalize_phone(item)
        if phone and PHONE_RE.fullmatch(phone):
            phones.add(phone)
    return phones


def _csv_values(raw: Optional[str]) -> Set[str]:
    return _phone_values(raw)


def _file_values(path: Optional[str]) -> Set[str]:
    if not path:
        return set()

    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return set()

    phones = set()
    for line in lines:
        phones.update(_phone_values(line.split("#", 1)[0]))
    return phones


def is_valid_internal_test_code(
    *,
    phone: str,
    submitted_code: str,
    enabled: bool,
    configured_code: Optional[str],
    allowed_phones_csv: Optional[str],
    allowed_phones_file: Optional[str] = None,
) -> bool:
    if not enabled:
        return False
    if not configured_code:
        return False
    if submitted_code != configured_code:
        return False

    allowed_phones = _csv_values(allowed_phones_csv) | _file_values(allowed_phones_file)
    return _normalize_phone(phone) in allowed_phones
