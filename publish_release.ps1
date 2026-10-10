param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubRepo
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) not found. Please install GitHub CLI and run gh auth login."
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found in PATH. Please install Git for Windows."
}

if (-not (Test-Path "release\DailyLog.exe")) {
    throw "release\DailyLog.exe not found. Run build_release.ps1 first."
}

if (-not (Test-Path "release\DailyLogUpdater.exe")) {
    throw "release\DailyLogUpdater.exe not found. Run build_release.ps1 first."
}

$main = Get-Content "main.py" -Raw

$match = [regex]::Match(
    $main,
    'APP_VERSION\s*=\s*["'']([^"'']+)["'']'
)

if (-not $match.Success) {
    throw "APP_VERSION was not found in main.py."
}

$version = $match.Groups[1].Value
$tag = "v$version"
$commit = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine source commit."
}

$hash = (
    Get-FileHash "release\DailyLog.exe" -Algorithm SHA256
).Hash.ToLowerInvariant()

$updaterHash = (
    Get-FileHash "release\DailyLogUpdater.exe" -Algorithm SHA256
).Hash.ToLowerInvariant()

$downloadUrl = "https://github.com/$GitHubRepo/releases/download/$tag/DailyLog.exe"

$manifest = [ordered]@{
    version = $version
    download_url = $downloadUrl
    sha256 = $hash
    updater_download_url = "https://github.com/$GitHubRepo/releases/download/$tag/DailyLogUpdater.exe"
    updater_sha256 = $updaterHash
    source_commit = $commit
    published_at = (
        Get-Date
    ).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    release_notes = @(
        "DailyLog $version"
    )
}

$manifest |
    ConvertTo-Json -Depth 5 |
    Set-Content -Encoding UTF8 "version.json"

Write-Host ""
Write-Host "========================================"
Write-Host " DailyLog Release Publisher"
Write-Host "========================================"
Write-Host "Version : $version"
Write-Host "SHA256  : $hash"
Write-Host "Repo    : $GitHubRepo"
Write-Host "Tag     : $tag"
Write-Host ""

$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
gh release view $tag --repo $GitHubRepo *> $null
$exists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $oldPreference

if ($exists) {
    throw "Release $tag already exists on GitHub. Increase APP_VERSION in main.py before publishing again."
}

gh release create $tag `
    "release\DailyLog.exe" `
    "release\DailyLogUpdater.exe" `
    "version.json" `
    --repo $GitHubRepo `
    --target $commit `
    --title "DailyLog $version" `
    --notes "DailyLog $version - production release with automatic updates, SA Sathorn status display, notification source management and admin device/session controls."

if ($LASTEXITCODE -ne 0) {
    throw "GitHub Release creation failed."
}

Write-Host ""
Write-Host "========================================"
Write-Host " RELEASE PUBLISHED SUCCESSFULLY"
Write-Host "========================================"
Write-Host "https://github.com/$GitHubRepo/releases/tag/$tag"
Write-Host ""
Write-Host "Installed DailyLog copies can now check for this release."
