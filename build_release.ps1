param(
    [string]$GitHubRepo = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
}

# Configure the public GitHub Releases endpoint used by installed copies.
# Example: .\build_release.ps1 -GitHubRepo "yourname/DailyLog"
if ($GitHubRepo.Trim()) {
    if ($GitHubRepo -notmatch '^[^/\s]+/[^/\s]+$') {
        throw "GitHubRepo ต้องอยู่ในรูป OWNER/REPOSITORY เช่น PearN/DailyLog"
    }
    $manifestUrl = "https://github.com/$GitHubRepo/releases/latest/download/version.json"
    @{ manifest_url = $manifestUrl } | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 "update_config.json"
    Write-Host "Update manifest: $manifestUrl"
}

.\.venv\Scripts\python.exe -m pip install -r requirements-main-build.txt
foreach ($spec in @("main.spec", "updater.spec")) {
    & .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm $spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $spec" }
}

New-Item -ItemType Directory -Force -Path "release" | Out-Null
Copy-Item "dist\DailyLog.exe" "release\DailyLog.exe" -Force
Copy-Item "dist\DailyLogUpdater.exe" "release\DailyLogUpdater.exe" -Force
Write-Host "Release ready: release\DailyLog.exe + release\DailyLogUpdater.exe"
