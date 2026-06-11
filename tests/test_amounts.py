"""Behavioral tests for the shared ISO 20022 amount helper."""

import unittest
from decimal import Decimal

from bankstatementparser._amounts import iso_decimal


class TestIsoDecimal(unittest.TestCase):
    def test_valid_amount_parses_exactly(self):
        self.assertEqual(
            iso_decimal("1234.56", context="test"), Decimal("1234.56")
        )

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(
            iso_decimal("  10.00 ", context="test"), Decimal("10.00")
        )

    def test_none_raises(self):
        with self.assertRaisesRegex(ValueError, "Missing amount"):
            iso_decimal(None, context="test")

    def test_blank_raises(self):
        with self.assertRaisesRegex(ValueError, "Missing amount"):
            iso_decimal("   ", context="test")

    def test_garbage_raises(self):
        with self.assertRaisesRegex(ValueError, "Invalid amount"):
            iso_decimal("12,34abc", context="test")

    def test_nan_raises(self):
        with self.assertRaisesRegex(ValueError, "Non-finite amount"):
            iso_decimal("NaN", context="test")

    def test_infinity_raises(self):
        with self.assertRaisesRegex(ValueError, "Non-finite amount"):
            iso_decimal("Infinity", context="test")


if __name__ == "__main__":
    unittest.main()
