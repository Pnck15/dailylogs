$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller

if (-not (Test-Path ".env")) {
    throw "ไม่พบไฟล์ .env - ต้องมี SUPABASE_URL และ SUPABASE_PUBLISHABLE_KEY ก่อน Build DailyLogNotify"
}

function Get-EnvValue {
    param(
        [string]$Name
    )

    $line = Get-Content ".env" |
        Where-Object {
            $_ -match "^\s*$([regex]::Escape($Name))\s*="
        } |
        Select-Object -First 1

    if (-not $line) {
        return ""
    }

    $value = ($line -split "=", 2)[1].Trim()
    $value = $value.Trim('"').Trim("'")
    return $value
}

$supabaseUrl = Get-EnvValue "SUPABASE_URL"
$supabaseKey = Get-EnvValue "SUPABASE_PUBLISHABLE_KEY"

if (-not $supabaseUrl) {
    throw "ไม่พบ SUPABASE_URL ใน .env"
}

if (-not $supabaseKey) {
    throw "ไม่พบ SUPABASE_PUBLISHABLE_KEY ใน .env"
}

$notifyEnv = @"
SUPABASE_URL=$supabaseUrl
SUPABASE_PUBLISHABLE_KEY=$supabaseKey
"@

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    (Join-Path $PSScriptRoot "notify.env"),
    $notifyEnv,
    $utf8NoBom
)

try {
    .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm DailyLogNotify.spec
    .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm updater.spec

    New-Item -ItemType Directory -Force -Path "release" | Out-Null
    Copy-Item "dist\DailyLogNotify.exe" "release\DailyLogNotify.exe" -Force
    Copy-Item "dist\DailyLogUpdater.exe" "release\DailyLogUpdater.exe" -Force
}
finally {
    if (Test-Path "notify.env") {
        Remove-Item "notify.env" -Force
    }
}

Write-Host ""
Write-Host "DailyLogNotify build complete:"
Write-Host "release\DailyLogNotify.exe"
Write-Host "release\DailyLogUpdater.exe"
Write-Host ""
Write-Host "Central receiver config was embedded in DailyLogNotify.exe."
