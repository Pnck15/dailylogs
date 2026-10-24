"""Offline flat-rate finance calculations and summary contract."""
import unittest
from decimal import Decimal
from car_finance_math import finance_quote, quote_text, DOWN_OPTIONS


class FinanceTests(unittest.TestCase):
    def test_example(self):
        q = finance_quote("315000", 20, 4, "1.68", 10)
        self.assertEqual(q["down"], Decimal("63000.00"))
        self.assertEqual(q["financed"], Decimal("252000.00"))
        self.assertEqual(q["months"], 48)
        self.assertEqual(q["monthly_principal"], Decimal("5250.00"))
        self.assertEqual(q["total_interest"], Decimal("16934.40"))
        self.assertEqual(q["monthly_interest"], Decimal("352.80"))
        self.assertEqual(q["monthly_payment"], Decimal("5602.80"))
        self.assertEqual(q["commission_gross"], Decimal("1693.44"))
        self.assertEqual(q["commission_base"], Decimal("1582.65"))
        self.assertEqual(q["commission_vat"], Decimal("110.79"))
        self.assertIn("5,602.80", quote_text(q, "EV", "กล้อง"))

    def test_zero_flat_interest(self):
        q = finance_quote(1000000, 50, 5, 0)
        self.assertEqual(q["monthly_payment"], Decimal("8333.33"))
        self.assertEqual(q["commission_gross"], Decimal("0.00"))

    def test_options_and_invalid_inputs(self):
        self.assertEqual(DOWN_OPTIONS, (5, 10, 15, 20, 25, 30, 35, 45, 50))
        for value in ("NaN", "-5", "infinity", "bad"):
            with self.assertRaises(ValueError):
                finance_quote(value, 20, 4, 2)
        with self.assertRaises(ValueError):
            finance_quote(1000000, 105, 5, 1)
        with self.assertRaises(ValueError):
            finance_quote(1000000, 20, 0, 1)


if __name__ == "__main__":
    unittest.main()
