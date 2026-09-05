"""Tests for entrypoint._parse_start_time."""
import subprocess
import sys
import unittest

from entrypoint import _parse_start_time


class ParseStartTimeTests(unittest.TestCase):
    def test_valid_midnight(self):
        self.assertEqual(_parse_start_time("00:00"), (0, 0))

    def test_valid_max(self):
        self.assertEqual(_parse_start_time("23:59"), (23, 59))

    def test_valid_evening(self):
        self.assertEqual(_parse_start_time("20:00"), (20, 0))

    def test_hour_too_high(self):
        with self.assertRaises(ValueError) as context:
            _parse_start_time("24:00")
        self.assertEqual(
            str(context.exception),
            "Invalid start_time: '24:00'. Expected hour 00-23 and minute 00-59.",
        )

    def test_hour_negative(self):
        with self.assertRaises(ValueError):
            _parse_start_time("-1:30")

    def test_minute_too_high(self):
        with self.assertRaises(ValueError):
            _parse_start_time("12:60")

    def test_minute_negative(self):
        with self.assertRaises(ValueError):
            _parse_start_time("12:-1")

    def test_non_numeric(self):
        with self.assertRaises(ValueError):
            _parse_start_time("abc")

    def test_missing_minute(self):
        with self.assertRaises(ValueError):
            _parse_start_time("12")

    def test_extra_parts(self):
        with self.assertRaises(ValueError):
            _parse_start_time("12:34:56")

    def test_empty_string(self):
        with self.assertRaises(ValueError):
            _parse_start_time("")

    def test_range_check_enforced_under_dash_O(self):
        # `python -O` strips `assert` statements. The range check must use an
        # explicit conditional so out-of-range values are still rejected.
        code = "\n".join(
            [
                "from webreport.data_collector.entrypoint import _parse_start_time",
                "try:",
                "    _parse_start_time('25:00')",
                "except ValueError:",
                "    print('rejected')",
                "else:",
                "    print('passed-through')",
            ]
        )
        result = subprocess.run(
            [sys.executable, "-O", "-c", code],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "rejected")


if __name__ == "__main__":
    unittest.main()
