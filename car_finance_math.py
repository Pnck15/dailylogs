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



RECEIPT_PRICE_TYPES = (
    ("ราคาดาวน์รถ / 首付款金额", "down_payment"),
    ("ราคาเต็มรถ / 整车原价", "full_price"),
)
RECEIPT_TRADE_IN = ("ไม่ระบุ / 未指定", "Carsome", "Just Car")

# key, Thai/Chinese field label, sign used by the receipt.
RECEIPT_ITEMS = (
    ("red_plate_deposit", "ค่ามัดจำป้ายแดง / 红牌押金", 1),
    ("booking_fee", "ค่าเงินจอง / 订车定金", -1),
    ("discount", "ส่วนลด / 优惠折扣", -1),
    ("tax_base", "ฐานคำนวณภาษี 7% / 7%税额计算基数", 0),
    ("other_discount", "ส่วนลดอื่นๆ รวม / 其他优惠合计", -1),
    ("film_upgrade", "ค่าอัพเกรดติดฟิล์ม / 车膜升级费", 1),
    ("film_discount", "ส่วนลดติดฟิล์ม / 车膜优惠", -1),
    ("insurance_premium", "ค่าเบี้ยประกันภัย / 保险费", 1),
    ("loan_insurance_premium", "ค่าเบี้ยประกันคุ้มครองวงเงินสินเชื่อ / 贷款保障保险费", 1),
    ("registration_fee", "ค่าจดทะเบียน / 车辆注册费", 1),
    ("other_accessories", "ค่าอุปกรณ์อื่นๆ / 其他配件费", 1),
)


def vehicle_receipt_quote(price, price_type="down_payment", trade_in="",
                          **charges):
    """Compute cash due on a vehicle receipt; no loan/interest calculations.

    Trade-in is an informational company selector ONLY because no trade-in
    amount or price offset was requested. Tax is tax_base * 7% (not price * 7%).
    All entry amounts are nonnegative; discount lines are subtracted.
    """
    valid_price_types = {code for _, code in RECEIPT_PRICE_TYPES}
    if price_type not in valid_price_types:
        raise ValueError("ประเภทของราคาไม่ถูกต้อง / 无效的金额类型")
    if trade_in not in ("", "Carsome", "Just Car"):
        raise ValueError("บริษัท Trade-in ไม่ถูกต้อง / 无效的置换服务商")
    if set(charges) - {key for key, _, _ in RECEIPT_ITEMS}:
        raise ValueError("พบรายการที่ไม่รองรับ / 存在不支持的收费项目")
    base = baht(money(price))
    if base <= 0:
        raise ValueError("กรุณากรอกยอดเงินตั้งต้นมากกว่า 0 / 请输入大于0的起始金额")
    amounts = {key: baht(money(charges.get(key, 0) or 0))
               for key, _, _ in RECEIPT_ITEMS}
    vat_seven = baht(amounts["tax_base"] * VAT)
    additions = sum(
        (amounts[key] for key, _, sign in RECEIPT_ITEMS if sign > 0),
        Decimal("0"),
    ) + vat_seven
    deductions = sum(
        (amounts[key] for key, _, sign in RECEIPT_ITEMS if sign < 0),
        Decimal("0"),
    )
    return {
        "price_type": price_type,
        "trade_in": trade_in or "ไม่ระบุ / 未指定",
        "price": base,
        **amounts,
        "vat_seven": vat_seven,
        "additions": baht(additions),
        "deductions": baht(deductions),
        "total_due": baht(base + additions - deductions),
    }


def vehicle_receipt_text(result, model="", accessories=""):
    """Plain-text bilingual breakdown used for colored results and Copy All."""
    r = result
    fmt = lambda value: f"{value:,.2f} บาท（泰铢）"
    type_label = dict((code, label) for label, code in RECEIPT_PRICE_TYPES)[
        r["price_type"]
    ]
    lines = [
        "ใบเสร็จรับเงินค่ารถ / 购车款收据",
        f"รุ่นรถ / 车型:   {model.strip() or '-'}",
        f"พร้อมอุปกรณ์ / 随车配件:   {accessories.strip() or '-'}",
        f"ประเภทของราคา / 金额类型:   {type_label}",
        f"Trade-in / 车辆置换:   {r['trade_in']}",
        f"ยอดตั้งต้น / 初始金额:   {fmt(r['price'])}",
    ]
    for key, label, sign in RECEIPT_ITEMS:
        if key == "tax_base":
            lines.append(f"{label}:   {fmt(r[key])}")
            lines.append(
                f"ภาษี 7% ที่บวกเพิ่ม / 加计7%税额:   +{fmt(r['vat_seven'])}"
            )
        else:
            prefix = "+" if sign > 0 else "-"
            lines.append(f"{label}:   {prefix}{fmt(r[key])}")
    lines.extend([
        f"รายการบวกทั้งหมด / 加项合计:   +{fmt(r['additions'])}",
        f"รายการหักทั้งหมด / 减项合计:   -{fmt(r['deductions'])}",
        f"ยอดสุทธิที่ต้องชำระ / 最终应付金额:   {fmt(r['total_due'])}",
        "",
        "หมายเหตุ / 备注: ยอดภาษีคำนวณจากฐานภาษีที่กรอก × 7% "
        "/ 税额根据输入的税基乘以7%计算",
        "Trade-in ระบุบริษัทเท่านั้น ไม่หักยอดขายรถ "
        "/ 置换仅记录服务商，不影响应付金额",
    ])
    return "\n".join(lines)
