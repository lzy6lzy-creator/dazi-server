from datetime import datetime, timezone
import unittest

from app.services.scheduler import next_hourly_run_at


class SchedulerTests(unittest.TestCase):
    def test_next_hourly_run_at_rounds_to_next_hour(self):
        now = datetime(2026, 6, 4, 14, 15, 30, tzinfo=timezone.utc)

        self.assertEqual(
            next_hourly_run_at(now),
            datetime(2026, 6, 4, 15, 0, 0, tzinfo=timezone.utc),
        )

    def test_next_hourly_run_at_moves_forward_from_exact_hour(self):
        now = datetime(2026, 6, 4, 14, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(
            next_hourly_run_at(now),
            datetime(2026, 6, 4, 15, 0, 0, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
