$ErrorActionPreference = 'Stop'

Write-Host '=== DailyLog Factory Setup ===' -ForegroundColor Cyan

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host 'ไม่พบ Python launcher (py). กรุณาติดตั้ง Python ก่อน' -ForegroundColor Red
    exit 1
}

if (-not (Test-Path '.venv')) {
    py -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host ''
Write-Host 'ติดตั้ง dependencies เสร็จแล้ว' -ForegroundColor Green
Write-Host 'ทดสอบโปรแกรม: .\.venv\Scripts\python.exe main.py'
Write-Host 'Build EXE:      .\.venv\Scripts\python.exe -m PyInstaller main.spec'
