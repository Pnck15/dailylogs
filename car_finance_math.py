"""Car down payment, flat-rate hire purchase and commission calculator.

Thai vehicle finance quotations use financed PRINCIPAL after deducting the
down payment. Flat-rate interest is NOT effective APR and excludes fees,
insurance, residuals and tax unless separately configured.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

SATANG = Decimal("0.01")
ONE = Decimal("1")
VAT = Decimal("0.07")
DOWN_OPTIONS = (5, 10, 15, 20, 25, 30, 35, 40, 45, 50)


def money(value):
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError("กรอกจำนวนเงินเป็นตัวเลข / 请输入有效金额") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("จำนวนเงินต้องไม่ติดลบและไม่ใช่ NaN/Infinity / 金额必须是非负的有限数值")
    return amount


def baht(value):
    return value.quantize(SATANG, rounding=ROUND_HALF_UP)


def finance_quote(price, down_percent, years, interest_percent,
                  commission_percent=0):
    """Return monetary amounts in baht, rounded only for display.

    Interest: financed_amount * annual flat rate * years.
    Commission: total interest * commission rate, gross includes VAT 7%.
    """
    price = money(price)
    dp = money(down_percent)
    yr = money(years)
    rate = money(interest_percent)
    cr = money(commission_percent)
    if price <= 0 or yr <= 0 or yr > 15:
        raise ValueError("ราคารถต้องมากกว่า 0 และผ่อน 1–15 ปี / 车价必须大于0，分期年限为1至15年")
    if dp > 100 or rate > 100 or cr > 100:
        raise ValueError("เปอร์เซ็นต์ต้องไม่เกิน 100 / 百分比不得超过100")
    months = int(yr * 12)
    if Decimal(months) != yr * 12 or months <= 0:
        raise ValueError("ระยะเวลาผ่อนต้องเป็นจำนวนเต็มเดือน / 分期期限必须为整月")
    down = price * dp / 100
    financed = price - down
    monthly_principal = financed / months
    annual_interest = financed * rate / 100
    total_interest = annual_interest * yr
    monthly_interest = total_interest / months
    monthly_payment = monthly_principal + monthly_interest
    commission_gross = total_interest * cr / 100
    commission_base = commission_gross / (ONE + VAT)
    commission_vat = commission_gross - commission_base
    return {
        "price": baht(price), "down_percent": dp, "years": yr,
        "months": months, "down": baht(down), "financed": baht(financed),
        "monthly_principal": baht(monthly_principal),
        "interest_percent": rate, "annual_interest": baht(annual_interest),
        "total_interest": baht(total_interest),
        "monthly_interest": baht(monthly_interest),
        "monthly_payment": baht(monthly_payment),
        "total_installments": baht(financed + total_interest),
        "commission_percent": cr, "commission_gross": baht(commission_gross),
        "commission_base": baht(commission_base),
        "commission_vat": baht(commission_gross) - baht(commission_base),
    }


def quote_text(result, model="", accessories=""):
    r = result
    def n(key):
        return format(r[key], ",.2f")
    return ("คำนวณเงินดาวน์ / ไฟแนนซ์รถยนต์ · 首付款及汽车分期付款计算\n"
            f"รุ่นรถ / 车型: {model.strip() or '-'}\n"
            f"พร้อมอุปกรณ์ / 随车配件: {accessories.strip() or '-'}\n"
            f"ราคาเต็มรถ / 整车原价: {n('price')} บาท（泰铢）\n"
            f"ดาวน์ / 首付款: {r['down_percent']}% = {n('down')} บาท（泰铢）\n"
            f"ยอดจัดไฟแนนซ์ / 贷款金额: {n('financed')} บาท（泰铢）\n"
            f"ระยะผ่อน / 分期期限: {r['years']} ปี（年）({r['months']} เดือน（月）)\n"
            f"เงินต้นต่อเดือน / 每月应还本金: {n('monthly_principal')} บาท（泰铢）\n"
            f"ดอกเบี้ย Flat Rate / 平息利率: {r['interest_percent']}% ต่อปี（年）\n"
            f"ดอกเบี้ยต่อปี / 年利息: {n('annual_interest')} บาท（泰铢）\n"
            f"ดอกเบี้ยรวม / 总利息: {n('total_interest')} บาท（泰铢）\n"
            f"ดอกเบี้ยต่อเดือน / 每月利息: {n('monthly_interest')} บาท（泰铢）\n"
            f"ค่างวดต่อเดือนสุทธิ / 每月应还款额: {n('monthly_payment')} บาท（泰铢）\n"
            f"ยอดรวมค่างวด / 分期付款总额: {n('total_installments')} บาท（泰铢）\n"
            f"ค่าคอมมิชชั่น / 佣金比例: {r['commission_percent']}%\n"
            f"ค่าคอมมิชชั่นรวม VAT 7% / 含7%增值税佣金: {n('commission_gross')} บาท（泰铢）\n"
            f"ค่าคอมมิชชั่นก่อน VAT / 未税佣金: {n('commission_base')} บาท（泰铢）\n"
            f"VAT 7% ของค่าคอมมิชชั่น / 佣金增值税（7%）: {n('commission_vat')} บาท（泰铢）\n"
            "\nหมายเหตุ / 备注: ค่างวดประมาณการแบบ Flat Rate / 月供按平息计算，"
            "ไม่รวมค่าธรรมเนียม/ประกัน/ส่วนลดที่ไม่ได้ระบุ / 不含未列明的手续费、保险及优惠").replace(": ", ":   ")


def vehicle_receipt_quote(price, down_percent, years, interest_percent,
                          down_discount=0, other_discount=0):
    """Discounts change ONLY what the customer pays as a down payment.

    Contracted financed principal and the resulting interest/instalments
    intentionally remain based on the ORIGINAL down-payment percentage.
    """
    result = finance_quote(price, down_percent, years, interest_percent)
    discount_down = baht(money(down_discount))
    discount_other = baht(money(other_discount))
    total_discount = baht(discount_down + discount_other)
    if total_discount > result["down"]:
        raise ValueError("ยอดส่วนลดรวมต้องไม่เกินเงินดาวน์ก่อนหักส่วนลด / 优惠总额不得超过优惠前首付款")
    result.update(
        down_discount=discount_down,
        other_discount=discount_other,
        total_discount=total_discount,
        receipt_down_due=baht(result["down"] - total_discount),
    )
    return result


def vehicle_receipt_text(result, model="", accessories=""):
    """Full plain-text breakdown for the receipt tab and clipboard."""
    r = result

    def n(key):
        return format(r[key], ",.2f")

    return (
        "คำนวณใบเสร็จรับเงินค่ารถ / 购车款收据计算\n"
        f"รุ่นรถ / 车型: {model.strip() or '-'}\n"
        f"พร้อมอุปกรณ์ / 随车配件: {accessories.strip() or '-'}\n"
        f"ราคาเต็มรถ / 整车原价: {n('price')} บาท（泰铢）\n"
        f"เงินดาวน์ก่อนส่วนลด / 优惠前首付款 ({r['down_percent']}%): {n('down')} บาท（泰铢）\n"
        f"ส่วนลดเงินดาวน์ / 首付款优惠: -{n('down_discount')} บาท（泰铢）\n"
        f"ส่วนลดอื่นๆ รวม / 其他优惠合计: -{n('other_discount')} บาท（泰铢）\n"
        f"ส่วนลดรวม / 优惠总额: {n('total_discount')} บาท（泰铢）\n"
        f"เงินดาวน์สุทธิที่ต้องชำระ / 实付首付款: {n('receipt_down_due')} บาท（泰铢）\n"
        f"ยอดจัดไฟแนนซ์ / 贷款金额: {n('financed')} บาท（泰铢）\n"
        f"ผ่อน / 分期期限: {r['years']} ปี（年）({r['months']} เดือน（月）)\n"
        f"ดอกเบี้ย Flat Rate / 平息利率: {r['interest_percent']}% ต่อปี（年）\n"
        f"ดอกเบี้ยรวม / 总利息: {n('total_interest')} บาท（泰铢）\n"
        f"เงินต้นต่อเดือน / 每月应还本金: {n('monthly_principal')} บาท（泰铢）\n"
        f"ดอกเบี้ยต่อเดือน / 每月利息: {n('monthly_interest')} บาท（泰铢）\n"
        f"ค่างวดต่อเดือนสุทธิ / 每月应还款额: {n('monthly_payment')} บาท（泰铢）\n"
        "\nหมายเหตุ / 备注: ส่วนลดหักจากเงินดาวน์เท่านั้น / 优惠仅抵扣首付款，"
        "不影响贷款金额及每月分期付款"
    ).replace(": ", ":   ")
