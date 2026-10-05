param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubRepo
)
$ErrorActionPreference="Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI not found." }
if (-not (Test-Path "release\DailyLogNotify.exe")) { throw "Build DailyLogNotify first." }
if (-not (Test-Path "release\DailyLogUpdater.exe")) { throw "DailyLogUpdater.exe not found." }

$source=Get-Content "dailylog_notify.py" -Raw
$m=[regex]::Match($source,'APP_VERSION\s*=\s*["'']([^"'']+)["'']')
if (-not $m.Success) { throw "APP_VERSION not found." }
$version=$m.Groups[1].Value
$tag="notify-v$version"
$hash=(Get-FileHash "release\DailyLogNotify.exe" -Algorithm SHA256).Hash.ToLowerInvariant()
$url="https://github.com/$GitHubRepo/releases/download/$tag/DailyLogNotify.exe"
$manifest=[ordered]@{
 version=$version
 download_url=$url
 sha256=$hash
 published_at=(Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
 release_notes=@("DailyLogNotify $version")
}
$json=$manifest|ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "notify-version.json"),$json,(New-Object System.Text.UTF8Encoding($false)))

$old=$ErrorActionPreference; $ErrorActionPreference="Continue"
gh release view $tag --repo $GitHubRepo *> $null
$exists=($LASTEXITCODE -eq 0)
$ErrorActionPreference=$old
if ($exists) { throw "Release $tag already exists. Increase APP_VERSION." }

gh release create $tag `
 "release\DailyLogNotify.exe" `
 "release\DailyLogUpdater.exe" `
 "notify-version.json" `
 --repo $GitHubRepo `
 --title "DailyLogNotify $version" `
 --notes "DailyLogNotify $version"
if ($LASTEXITCODE -ne 0) { throw "GitHub Release creation failed." }
Write-Host "Published: https://github.com/$GitHubRepo/releases/tag/$tag"
