param(
    [string]$GitHubRepo = "Pnck15/dailylogs"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "========================================"
Write-Host " DailyLog - BUILD ALL PRODUCTION"
Write-Host "========================================"
Write-Host ""

if (-not (Test-Path ".env")) {
    throw "ไม่พบไฟล์ .env - ต้องมี SUPABASE_URL และ SUPABASE_PUBLISHABLE_KEY ก่อน Build"
}

if (Test-Path "release") {
    Remove-Item "release" -Recurse -Force
}

New-Item -ItemType Directory -Force -Path "release" | Out-Null

Write-Host "[1/2] Building DailyLog.exe..."
& "$PSScriptRoot\build_release.ps1" -GitHubRepo $GitHubRepo

Write-Host ""
Write-Host "[2/2] Building DailyLogNotify.exe..."
& "$PSScriptRoot\build_notify.ps1"

$required = @(
    "release\DailyLog.exe",
    "release\DailyLogNotify.exe",
    "release\DailyLogUpdater.exe"
)

foreach ($path in $required) {
    if (-not (Test-Path $path)) {
        throw "Build incomplete: $path not found."
    }
}

$main = Get-Content "main.py" -Raw
$mainMatch = [regex]::Match(
    $main,
    'APP_VERSION\s*=\s*["'']([^"'']+)["'']'
)

$notify = Get-Content "dailylog_notify.py" -Raw
$notifyMatch = [regex]::Match(
    $notify,
    'APP_VERSION\s*=\s*["'']([^"'']+)["'']'
)

$mainVersion = if ($mainMatch.Success) {
    $mainMatch.Groups[1].Value
} else {
    "unknown"
}

$notifyVersion = if ($notifyMatch.Success) {
    $notifyMatch.Groups[1].Value
} else {
    "unknown"
}

Write-Host ""
Write-Host "========================================"
Write-Host " BUILD ALL SUCCESS"
Write-Host "========================================"
Write-Host "DailyLog       : $mainVersion"
Write-Host "DailyLogNotify : $notifyVersion"
Write-Host ""
Write-Host "Artifacts:"
Get-ChildItem "release" | ForEach-Object {
    Write-Host (" - " + $_.Name)
}
