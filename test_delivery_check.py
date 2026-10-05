import requests
from datetime import datetime

URL = "https://script.google.com/macros/s/AKfycbzTLZ0pe7uS0VACaz5IySq0jwVZsNehdWJlGrEfxlgMnZAIaK7zArf-Fc0wGextmx5wyA/exec"

response = requests.get(URL, timeout=30)

data = response.json()

delivery_data = data["data"]

today = datetime.now().strftime("%d/%m/%Y")

print("วันนี้:", today)
print()

found = 0

for item in delivery_data:

    delivery_date = item["delivery_date"]

    if delivery_date == today:

        found += 1

        print("🚗 รถที่ต้องส่งวันนี้")
        print("VIN:", item["vin"])
        print("Customer:", item["customer"])
        print("Delivery Date:", item["delivery_date"])
        print()

print("จำนวนรถที่ต้องส่งวันนี้:", found)