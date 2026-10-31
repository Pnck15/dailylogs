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

    def test_manual_down_amount_changes_financed_principal(self):
        # Nonpercentage down payment; percent should be derived for display.
        manual = finance_quote("315000", None, 4, "1.68", 10,
                               down_amount="60000")
        self.assertEqual(manual["down"], Decimal("60000.00"))
        self.assertEqual(manual["financed"], Decimal("255000.00"))
        self.assertEqual(manual["months"], 48)
        self.assertEqual(manual["monthly_principal"], Decimal("5312.50"))
        self.assertEqual(manual["total_interest"], Decimal("17136.00"))
        self.assertEqual(manual["monthly_interest"], Decimal("357.00"))
        self.assertEqual(manual["monthly_payment"], Decimal("5669.50"))
        self.assertEqual(manual["down_input_mode"], "amount")
        self.assertEqual(manual["down_percent"].quantize(Decimal("0.01")),
                         Decimal("19.05"))
        report = quote_text(manual, "EV")
        self.assertIn("自定义金额", report)
        self.assertIn("60,000.00", report)
        self.assertIn("19.05%", report)
        self.assertIn("5,669.50", report)
        self.assertEqual(
            finance_quote("315000", 20, 4, "1.68")["down_input_mode"],
            "percent",
        )

    def test_credit_protection_insurance_increases_cash_down_only(self):
        # Customer example: 1,137,000 - 533,048 = 603,952 financed.
        # 16,952 insurance is paid separately ON TOP of the cash down.
        q = finance_quote("1137000", None, 4, "1.88",
                          down_amount="533048",
                          loan_insurance_premium="16952")
        self.assertEqual(q["down"], Decimal("533048.00"))
        self.assertEqual(q["loan_insurance_premium"], Decimal("16952.00"))
        self.assertEqual(q["down_total_including_insurance"], Decimal("550000.00"))
        self.assertEqual(q["financed"], Decimal("603952.00"))
        self.assertEqual(q["months"], 48)
        self.assertEqual(q["monthly_payment"], Decimal("13528.52"))
        report = quote_text(q)
        self.assertIn("533,048.00", report)
        self.assertIn("+16,952.00", report)
        self.assertIn("550,000.00", report)
        self.assertIn("603,952.00", report)
        self.assertIn("13,528.52", report)
        self.assertIn("13,529", report)
        without = finance_quote("1137000", None, 4, "1.88",
                                down_amount="533048")
        self.assertEqual(q["financed"], without["financed"])
        self.assertEqual(q["monthly_payment"], without["monthly_payment"])
        percent = finance_quote("1000000", 20, 4, "1.88",
                                loan_insurance_premium="16952")
        self.assertEqual(percent["down"], Decimal("200000.00"))
        self.assertEqual(percent["down_total_including_insurance"], Decimal("216952.00"))
        self.assertEqual(percent["financed"], Decimal("800000.00"))
        self.assertEqual(without["loan_insurance_premium"], Decimal("0.00"))
        for invalid in ("-1", "NaN", "Infinity", "abc"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                finance_quote("1137000", 20, 4, "1.88",
                              loan_insurance_premium=invalid)

    def test_kbank_gross_commission_override_and_net_payout(self):
        # Bank-provided actual gross 3,666 is slightly below 8% estimated
        # from the flat interest (3,666.41). 3% is withheld on pre-VAT base.
        q = finance_quote("771550", None, 3, "1.98", 8,
                          down_amount="0", bank="Kbank",
                          sale_type="Trade in",
                          commission_gross_amount="3666")
        self.assertEqual(q["financed"], Decimal("771550.00"))
        self.assertEqual(q["monthly_payment"], Decimal("22705.00"))
        self.assertEqual(q["total_interest"], Decimal("45830.07"))
        self.assertEqual(q["commission_gross"], Decimal("3666.00"))
        self.assertEqual(q["commission_base"], Decimal("3426.17"))
        self.assertEqual(q["commission_withholding"], Decimal("102.79"))
        self.assertEqual(q["commission_net"], Decimal("3563.21"))
        self.assertEqual(q["bank_payout_total"], Decimal("775113.21"))
        self.assertEqual(q["commission_input_mode"], "amount")
        self.assertAlmostEqual(float(q["commission_percent"]), 8.0, places=2)
        report = quote_text(q, "Nissan")
        self.assertIn("775,113.21", report)
        self.assertIn("3,563.21", report)
        self.assertIn("Trade in", report)
        self.assertIn("Kbank", report)
        self.assertNotIn("หมายเหตุ / 备注", report)
        estimated = finance_quote("771550", None, 3, "1.98", 8,
                                  down_amount="0", bank="Kbank")
        self.assertEqual(estimated["commission_gross"], Decimal("3666.41"))
        self.assertEqual(estimated["monthly_payment"], q["monthly_payment"])
        self.assertEqual(estimated["commission_input_mode"], "percent")
        for kwargs in ({"bank": "Unknown"}, {"sale_type": "Unknown"},
                       {"commission_gross_amount": "-10"},
                       {"commission_gross_amount": "NaN"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                finance_quote(315000, 20, 4, 1.88, **kwargs)

    def test_manual_down_amount_validation(self):
        for amount in ("", "-1", "NaN", "Infinity", "315000.01", "xyz"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                finance_quote(315000, None, 4, 1.68, down_amount=amount)
        full_down = finance_quote(315000, None, 4, 1.68,
                                  down_amount="315000")
        self.assertEqual(full_down["financed"], Decimal("0.00"))
        self.assertEqual(full_down["monthly_payment"], Decimal("0.00"))
        zero_down = finance_quote(315000, None, 4, 1.68,
                                  down_amount="0")
        self.assertEqual(zero_down["financed"], Decimal("315000.00"))

    def test_zero_flat_interest(self):
        q = finance_quote(1000000, 50, 5, 0)
        self.assertEqual(q["monthly_payment"], Decimal("8333.33"))
        self.assertEqual(q["commission_gross"], Decimal("0.00"))

    def test_receipt_additions_deductions_and_tax(self):
        # Receipt is no longer an interest/financing calculation.
        receipt = vehicle_receipt_quote(
            "315000", price_type="full_price", trade_in="Carsome",
            red_plate_deposit="2000",
            booking_fee="5000",
            discount="10000",
            tax_base="10000",
            other_discount="2500",
            film_upgrade="3000",
            film_discount="500",
            insurance_premium="8000",
            loan_insurance_premium="1000",
            registration_fee="1500",
            other_accessories="500",
        )
        self.assertEqual(receipt["vat_seven"], Decimal("700.00"))
        self.assertEqual(receipt["additions"], Decimal("15700.00"))
        self.assertEqual(receipt["deductions"], Decimal("19000.00"))
        self.assertEqual(receipt["total_due"], Decimal("311700.00"))
        self.assertEqual(receipt["price_type"], "full_price")
        self.assertEqual(receipt["trade_in"], "Carsome")
        text = vehicle_receipt_text(receipt, "EV", "กล้อง")
        self.assertIn("311,700.00", text)
        self.assertIn("Carsome", text)
        self.assertIn("税额", text)
        self.assertNotIn("ดอกเบี้ย", text)
        self.assertNotIn("年息", text)
        self.assertNotIn("贷款金额", text)
        self.assertNotIn("每月", text)

    def test_loan_insurance_deducted_from_down_payment(self):
        # Changing only this fee must REDUCE (not increase) the cash due.
        baseline = vehicle_receipt_quote("63000", price_type="down_payment")
        with_insurance = vehicle_receipt_quote(
            "63000", price_type="down_payment",
            loan_insurance_premium="2500",
        )
        self.assertEqual(baseline["total_due"], Decimal("63000.00"))
        self.assertEqual(with_insurance["total_due"], Decimal("60500.00"))
        self.assertEqual(with_insurance["deductions"], Decimal("2500.00"))
        self.assertEqual(with_insurance["additions"], Decimal("0.00"))
        details = vehicle_receipt_text(with_insurance)
        self.assertIn(
            "贷款保障保险费（抵扣首付款）:   -2,500.00", details,
        )
        # Regular insurance remains an ADDITION.
        with_both = vehicle_receipt_quote(
            "63000", price_type="down_payment",
            insurance_premium="1000",
            loan_insurance_premium="2500",
        )
        self.assertEqual(with_both["total_due"], Decimal("61500.00"))

    def test_receipt_trade_in_is_informational(self):
        a = vehicle_receipt_quote("100000", red_plate_deposit=500,
                                  booking_fee=1000, tax_base=1)
        b = vehicle_receipt_quote("100000", trade_in="Just Car",
                                  red_plate_deposit=500,
                                  booking_fee=1000, tax_base=1)
        self.assertEqual(a["total_due"], b["total_due"])
        self.assertEqual(a["vat_seven"], Decimal("0.07"))
        self.assertEqual(a["total_due"], Decimal("99500.07"))
        self.assertEqual(b["trade_in"], "Just Car")
        self.assertIn("Just Car", vehicle_receipt_text(b))

    def test_receipt_invalid_amounts_and_types(self):
        for bad in ("-1", "NaN", "Infinity", "abc"):
            with self.subTest(amount=bad), self.assertRaises(ValueError):
                vehicle_receipt_quote("100000", film_discount=bad)
        with self.assertRaises(ValueError):
            vehicle_receipt_quote(0)
        with self.assertRaises(ValueError):
            vehicle_receipt_quote("100000", price_type="invalid")
        with self.assertRaises(ValueError):
            vehicle_receipt_quote("100000", trade_in="Other")
        with self.assertRaises(ValueError):
            vehicle_receipt_quote("100000", unlisted_fee=999)

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
