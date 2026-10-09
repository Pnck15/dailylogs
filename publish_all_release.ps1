param(
    [string]$GitHubRepo = "Pnck15/dailylogs"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) not found. Install GitHub CLI and run gh auth login."
}

$main = Get-Content "main.py" -Raw
$mainMatch = [regex]::Match(
    $main,
    'APP_VERSION\s*=\s*["'']([^"'']+)["'']'
)
if (-not $mainMatch.Success) {
    throw "APP_VERSION not found in main.py"
}
$mainVersion = $mainMatch.Groups[1].Value
$mainTag = "v$mainVersion"

$notify = Get-Content "dailylog_notify.py" -Raw
$notifyMatch = [regex]::Match(
    $notify,
    'APP_VERSION\s*=\s*["'']([^"'']+)["'']'
)
if (-not $notifyMatch.Success) {
    throw "APP_VERSION not found in dailylog_notify.py"
}
$notifyVersion = $notifyMatch.Groups[1].Value
$notifyTag = "notify-v$notifyVersion"

$required = @(
    "release\DailyLog.exe",
    "release\DailyLogNotify.exe",
    "release\DailyLogUpdater.exe"
)
foreach ($path in $required) {
    if (-not (Test-Path $path)) {
        throw "Missing $path. Run build_all_release.ps1 first."
    }
}

function Test-ReleaseExists {
    param([string]$Tag)

    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    gh release view $Tag --repo $GitHubRepo *> $null
    $exists = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $old

    return $exists
}

if (Test-ReleaseExists $notifyTag) {
    throw "Release $notifyTag already exists. Increase DailyLogNotify APP_VERSION before publishing."
}

if (Test-ReleaseExists $mainTag) {
    throw "Release $mainTag already exists. Increase DailyLog APP_VERSION before publishing."
}

Write-Host ""
Write-Host "========================================"
Write-Host " DailyLog - PUBLISH ALL PRODUCTION"
Write-Host "========================================"
Write-Host "Notify : $notifyTag"
Write-Host "Main   : $mainTag"
Write-Host ""

# Publish Notify first. Existing DailyLogNotify clients search notify-v* releases.
& "$PSScriptRoot\publish_notify_release.ps1" -GitHubRepo $GitHubRepo

# Publish DailyLog last so the main-app latest release stays vX.Y.Z.
& "$PSScriptRoot\publish_release.ps1" -GitHubRepo $GitHubRepo

Write-Host ""
Write-Host "========================================"
Write-Host " PUBLISH ALL SUCCESS"
Write-Host "========================================"
Write-Host "DailyLog       : $mainTag"
Write-Host "DailyLogNotify : $notifyTag"
Write-Host "Developed by 王纯真"
