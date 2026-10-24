"""Car down payment, flat-rate hire purchase and commission calculator.

Thai vehicle finance quotations use financed PRINCIPAL after deducting the
down payment. Flat-rate interest is NOT effective APR and excludes fees,
insurance, residuals and tax unless separately configured.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

SATANG = Decimal("0.01")
ONE = Decimal("1")
VAT = Decimal("0.07")
DOWN_OPTIONS = (5, 10, 15, 20, 25, 30, 35, 45, 50)


def money(value):
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError("กรอกจำนวนเงินเป็นตัวเลข") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("จำนวนเงินต้องไม่ติดลบและไม่ใช่ NaN/Infinity")
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
        raise ValueError("ราคารถต้องมากกว่า 0 และผ่อน 1–15 ปี")
    if dp > 100 or rate > 100 or cr > 100:
        raise ValueError("เปอร์เซ็นต์ต้องไม่เกิน 100")
    months = int(yr * 12)
    if Decimal(months) != yr * 12 or months <= 0:
        raise ValueError("ระยะเวลาผ่อนต้องเป็นจำนวนเต็มเดือน")
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
    return ("คำนวณเงินดาวน์ / ไฟแนนซ์รถยนต์\n"
            f"รุ่นรถ: {model.strip() or '-'}\n"
            f"พร้อมอุปกรณ์: {accessories.strip() or '-'}\n"
            f"ราคาเต็มรถ: {n('price')} บาท\n"
            f"ดาวน์: {r['down_percent']}% = {n('down')} บาท\n"
            f"ยอดจัดไฟแนนซ์: {n('financed')} บาท\n"
            f"ระยะผ่อน: {r['years']} ปี ({r['months']} เดือน)\n"
            f"เงินต้นต่อเดือน: {n('monthly_principal')} บาท\n"
            f"ดอกเบี้ย Flat Rate: {r['interest_percent']}% ต่อปี\n"
            f"ดอกเบี้ยต่อปี: {n('annual_interest')} บาท\n"
            f"ดอกเบี้ยรวม: {n('total_interest')} บาท\n"
            f"ดอกเบี้ยต่อเดือน: {n('monthly_interest')} บาท\n"
            f"ค่างวดต่อเดือน: {n('monthly_payment')} บาท\n"
            f"ยอดรวมค่างวด: {n('total_installments')} บาท\n"
            f"ค่าคอมมิชชั่น: {r['commission_percent']}%\n"
            f"ค่าคอมมิชชั่นรวม VAT 7%: {n('commission_gross')} บาท\n"
            f"ค่าคอมมิชชั่นก่อน VAT: {n('commission_base')} บาท\n"
            f"VAT 7% ของค่าคอมมิชชั่น: {n('commission_vat')} บาท\n"
            "หมายเหตุ: ค่างวดประมาณการแบบ Flat Rate "
            "ไม่รวมค่าธรรมเนียม/ประกัน/ส่วนลดที่ไม่ได้ระบุ")
