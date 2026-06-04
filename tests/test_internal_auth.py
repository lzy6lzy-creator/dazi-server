import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.api.auth_helpers import is_valid_internal_test_code


class InternalAuthTests(unittest.TestCase):
    def test_internal_test_code_requires_whitelisted_phone(self):
        self.assertTrue(is_valid_internal_test_code(
            phone="13800000000",
            submitted_code="246810",
            enabled=True,
            configured_code="246810",
            allowed_phones_csv="13800000000, 13900000000",
        ))
        self.assertFalse(is_valid_internal_test_code(
            phone="13700000000",
            submitted_code="246810",
            enabled=True,
            configured_code="246810",
            allowed_phones_csv="13800000000, 13900000000",
        ))

    def test_internal_test_code_is_disabled_without_mode_or_code(self):
        self.assertFalse(is_valid_internal_test_code(
            phone="13800000000",
            submitted_code="246810",
            enabled=False,
            configured_code="246810",
            allowed_phones_csv="13800000000",
        ))
        self.assertFalse(is_valid_internal_test_code(
            phone="13800000000",
            submitted_code="",
            enabled=True,
            configured_code="",
            allowed_phones_csv="13800000000",
        ))

    def test_internal_test_code_accepts_runtime_phone_file(self):
        with TemporaryDirectory() as tmp:
            phones_file = Path(tmp) / "internal_test_phones.txt"
            phones_file.write_text(
                "# comments are ignored\n"
                "13800000000\n"
                "13900000000, 13700000000\n",
                encoding="utf-8",
            )

            self.assertTrue(is_valid_internal_test_code(
                phone="13700000000",
                submitted_code="246810",
                enabled=True,
                configured_code="246810",
                allowed_phones_csv="",
                allowed_phones_file=str(phones_file),
            ))

    def test_internal_test_code_reloads_runtime_phone_file_changes(self):
        with TemporaryDirectory() as tmp:
            phones_file = Path(tmp) / "internal_test_phones.txt"
            phones_file.write_text("13800000000\n", encoding="utf-8")

            self.assertTrue(is_valid_internal_test_code(
                phone="13800000000",
                submitted_code="246810",
                enabled=True,
                configured_code="246810",
                allowed_phones_csv="",
                allowed_phones_file=str(phones_file),
            ))

            phones_file.write_text("13900000000\n", encoding="utf-8")

            self.assertFalse(is_valid_internal_test_code(
                phone="13800000000",
                submitted_code="246810",
                enabled=True,
                configured_code="246810",
                allowed_phones_csv="",
                allowed_phones_file=str(phones_file),
            ))
            self.assertTrue(is_valid_internal_test_code(
                phone="13900000000",
                submitted_code="246810",
                enabled=True,
                configured_code="246810",
                allowed_phones_csv="",
                allowed_phones_file=str(phones_file),
            ))


if __name__ == "__main__":
    unittest.main()
