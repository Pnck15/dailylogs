import requests

URL = "https://script.google.com/macros/s/AKfycbzTLZ0pe7uS0VACaz5IySq0jwVZsNehdWJlGrEfxlgMnZAIaK7zArf-Fc0wGextmx5wyA/exec"

response = requests.get(URL, timeout=30)

print("Status:", response.status_code)

data = response.json()

print("Success:", data["success"])
print("Count:", data["count"])

print()

# เอาข้อมูลออกมาเป็นตัวแปร
delivery_data = data["data"]

print("จำนวนข้อมูลใน Python:", len(delivery_data))

print()
print("รายการแรก")
print("Row:", delivery_data[0]["row"])
print("VIN:", delivery_data[0]["vin"])
print("Customer:", delivery_data[0]["customer"])
print("Pay Day:", delivery_data[0]["pay_day"])
print("Delivery Date:", delivery_data[0]["delivery_date"])