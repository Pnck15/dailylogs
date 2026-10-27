"""Offline flat-rate finance calculations and summary contract."""
import unittest
from decimal import Decimal
from car_finance_math import (finance_quote, quote_text, DOWN_OPTIONS,
                              vehicle_receipt_quote, vehicle_receipt_text)


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
        self.assertIn("贷款金额", quote_text(q, "EV", "กล้อง"))
        self.assertIn("未税佣金", quote_text(q, "EV", "กล้อง"))

    def test_zero_flat_interest(self):
        q = finance_quote(1000000, 50, 5, 0)
        self.assertEqual(q["monthly_payment"], Decimal("8333.33"))
        self.assertEqual(q["commission_gross"], Decimal("0.00"))

    def test_vehicle_receipt_discounts_change_cash_down_only(self):
        base = finance_quote("315000", 20, 4, "1.68")
        invoice = vehicle_receipt_quote("315000", 20, 4, "1.68", "5000", "2500")
        self.assertEqual(invoice["down"], Decimal("63000.00"))
        self.assertEqual(invoice["down_discount"], Decimal("5000.00"))
        self.assertEqual(invoice["other_discount"], Decimal("2500.00"))
        self.assertEqual(invoice["total_discount"], Decimal("7500.00"))
        self.assertEqual(invoice["receipt_down_due"], Decimal("55500.00"))
        for key in ("financed", "monthly_principal", "total_interest",
                    "monthly_interest", "monthly_payment", "months"):
            self.assertEqual(invoice[key], base[key], key)
        text = vehicle_receipt_text(invoice, "EV", "กล้อง")
        self.assertIn("55,500.00", text)
        self.assertIn("ยอดจัดไฟแนนซ์ / 贷款金额:   252,000.00", text)
        self.assertIn("ค่างวดต่อเดือนสุทธิ / 每月应还款额:   5,602.80", text)
        self.assertNotIn("คอมมิชชั่น", text)

    def test_vehicle_receipt_zero_and_discount_limits(self):
        receipt = vehicle_receipt_quote("100000", 10, 3, 2)
        self.assertEqual(receipt["receipt_down_due"], Decimal("10000.00"))
        self.assertEqual(receipt["total_discount"], Decimal("0.00"))
        same_as_down = vehicle_receipt_quote(100000, 10, 3, 2, 9999, 1)
        self.assertEqual(same_as_down["receipt_down_due"], Decimal("0.00"))
        with self.assertRaisesRegex(ValueError, "ส่วนลดรวม"):
            vehicle_receipt_quote(100000, 10, 3, 2, 10001, 0)
        for bad in ("-1", "NaN", "Infinity", "abc"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                vehicle_receipt_quote(100000, 10, 3, 2, bad, 0)

    def test_options_and_invalid_inputs(self):
        self.assertEqual(DOWN_OPTIONS, (5, 10, 15, 20, 25, 30, 35, 40, 45, 50))
        for value in ("NaN", "-5", "infinity", "bad"):
            with self.assertRaises(ValueError):
                finance_quote(value, 20, 4, 2)
        with self.assertRaises(ValueError):
            finance_quote(1000000, 105, 5, 1)
        with self.assertRaises(ValueError):
            finance_quote(1000000, 20, 0, 1)


if __name__ == "__main__":
    unittest.main()
