$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm DailyLogNotify.spec

New-Item -ItemType Directory -Force -Path "release" | Out-Null
Copy-Item "dist\DailyLogNotify.exe" "release\DailyLogNotify.exe" -Force

Write-Host ""
Write-Host "DailyLogNotify build complete:"
Write-Host "release\DailyLogNotify.exe"
