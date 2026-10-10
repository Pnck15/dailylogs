#Requires -Version 5.1
param(
    [string]$GitHubRepo = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        Write-Host "Creating project virtual environment..."
        & py -3 -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Cannot create .venv. Install Python 3.11-3.14 and retry."
        }
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Missing .venv\Scripts\python.exe"
    }

    # Preserve the existing public GitHub manifest used by installed copies.
    if ($GitHubRepo.Trim()) {
        if ($GitHubRepo -notmatch '^[^/\s]+/[^/\s]+$') {
            throw "GitHubRepo must be OWNER/REPOSITORY, e.g. Pnck15/dailylogs"
        }
        $manifestUrl = "https://github.com/$GitHubRepo/releases/latest/download/version.json"
        @{ manifest_url = $manifestUrl } | ConvertTo-Json -Compress |
            Set-Content -Encoding UTF8 "update_config.json"
        Write-Host "Update manifest: $manifestUrl"
    }

    Write-Host "[1/3] Installing compatible build requirements..."
    & $python -m pip install --disable-pip-version-check --upgrade -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed. Build stopped to avoid packaging stale dependencies."
    }

    & $python -c "import sys, PySide6, PyInstaller; print('Python:', sys.version.split()[0]); print('PySide6:', PySide6.__version__); print('PyInstaller:', PyInstaller.__version__)"
    if ($LASTEXITCODE -ne 0) {
        throw "Build environment validation failed."
    }

    Write-Host "[2/3] Building DailyLog.exe..."
    & $python -m PyInstaller --clean --noconfirm main.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed to build DailyLog.exe."
    }

    Write-Host "[3/3] Building DailyLogUpdater.exe..."
    & $python -m PyInstaller --clean --noconfirm updater.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed to build DailyLogUpdater.exe."
    }

    foreach ($file in @("DailyLog.exe", "DailyLogUpdater.exe")) {
        $distFile = Join-Path $PSScriptRoot ("dist\" + $file)
        if (-not (Test-Path -LiteralPath $distFile -PathType Leaf)) {
            throw "Missing build output: $distFile"
        }
    }

    New-Item -ItemType Directory -Force -Path "release" | Out-Null
    Copy-Item "dist\DailyLog.exe" "release\DailyLog.exe" -Force
    Copy-Item "dist\DailyLogUpdater.exe" "release\DailyLogUpdater.exe" -Force
    Write-Host "Release ready: release\DailyLog.exe + release\DailyLogUpdater.exe"
}
finally {
    Pop-Location
}
