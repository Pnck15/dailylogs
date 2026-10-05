import sys
from datetime import datetime
import requests
from PySide6.QtWidgets import QApplication, QMessageBox

SATHORN_URL = "https://script.google.com/macros/s/AKfycbwOUICgXh-6HykkMc4lMT1Xf12fdne8FO0769Dew2ZoKm2xVSeTHNMRaPHNlZmC_CvHYw/exec"
SRINAKARIN_URL = ""  # ใส่ Apps Script Web App URL ของ Srinakarin ตรงนี้


def get_delivery_data(url):
    if not url:
        raise ValueError("ยังไม่ได้ใส่ Apps Script URL")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(data.get("error", "Apps Script returned success=false"))
    return data.get("data", [])


def find_today_deliveries(delivery_data):
    today = datetime.now().strftime("%d/%m/%Y")
    return [item for item in delivery_data if item.get("delivery_date") == today]


def show_result(parent, title, delivery_data):
    today_deliveries = find_today_deliveries(delivery_data)
    if today_deliveries:
        message = "🚗 รถที่ต้องส่งวันนี้\n\n"
        for item in today_deliveries:
            message += (
                f"VIN: {item.get('vin', '-') }\n"
                f"Customer: {item.get('customer', '-') }\n"
                f"Delivery Date: {item.get('delivery_date', '-') }\n\n"
            )
    else:
        message = "วันนี้ไม่มีรถที่ต้องส่ง"
    QMessageBox.information(parent, title, message)


app = QApplication(sys.argv)

for title, url in (("Sale Deli Sathorn", SATHORN_URL), ("Sale Deli Srinakarin", SRINAKARIN_URL)):
    if not url:
        continue
    try:
        show_result(None, title, get_delivery_data(url))
    except Exception as error:
        QMessageBox.critical(None, title, f"อ่านข้อมูลไม่สำเร็จ\n\n{error}")

sys.exit(0)

