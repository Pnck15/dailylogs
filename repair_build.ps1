#Requires -Version 5.1
<#
Repair local legacy PySide6 pins before using existing Windows build scripts.
This script is intended for Python 3.14+ environments and never edits Python
application source files. Local scripts missing from GitHub are preserved.
#>
[CmdletBinding()]
param(
    [switch]$BuildOnly,
    [switch]$Publish,
    [string]$GitHubRepo = "Pnck15/dailylogs"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($BuildOnly -and $Publish) {
    throw "Choose -BuildOnly or -Publish, not both."
}

Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Missing .venv\Scripts\python.exe. Create the project venv first."
    }

    $version = (& $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Cannot query Python version." }
    Write-Host "Project Python: $version"
    $parts = $version.Split('.')
    $isPython314 = ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 14)

    if ($isPython314) {
        Write-Host "Checking local build scripts for incompatible PySide6 pins..."
        $targets = @()
        foreach ($folder in @(".", "scripts", "build_scripts", "packaging")) {
            if (-not (Test-Path $folder -PathType Container)) { continue }
            if ($folder -eq ".") {
                $targets += @(Get-ChildItem -LiteralPath $folder -File)
            } else {
                $targets += @(Get-ChildItem -LiteralPath $folder -File -Recurse)
            }
        }

        $legacyPin = '(?i)\bPySide6\s*==\s*6\.(?:[0-9]\.\d+(?:\.\d+)?|10\.0)\b'
        $backupRoot = Join-Path $PSScriptRoot (".build_repair_backups\" + (Get-Date -Format "yyyyMMdd_HHmmss"))
        $changed = 0
        foreach ($file in $targets) {
            $scriptFile = $file.Extension -in @(".ps1", ".cmd", ".bat")
            $dependencyFile = (
                $file.Extension -in @(".txt", ".in") -and
                $file.Name -match '(?i)requirements|dependencies'
            )
            if (-not ($scriptFile -or $dependencyFile)) { continue }
            if ($file.Name -eq "repair_build.ps1") { continue }

            $old = [System.IO.File]::ReadAllText($file.FullName)
            $new = [regex]::Replace($old, $legacyPin, "PySide6==6.10.2")
            if ($old -ceq $new) { continue }

            $relative = $file.FullName.Substring($PSScriptRoot.Length).TrimStart('\', '/')
            $backup = Join-Path $backupRoot $relative
            $backupDir = Split-Path -Parent $backup
            New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $backup -Force

            $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
            $utf16le = $bytes.Length -ge 2 -and $bytes[0] -eq 255 -and $bytes[1] -eq 254
            $utf16be = $bytes.Length -ge 2 -and $bytes[0] -eq 254 -and $bytes[1] -eq 255
            $utf8bom = $bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191
            if ($utf16le) { $encoding = New-Object System.Text.UnicodeEncoding($false, $true) }
            elseif ($utf16be) { $encoding = New-Object System.Text.UnicodeEncoding($true, $true) }
            else { $encoding = New-Object System.Text.UTF8Encoding($utf8bom) }

            [System.IO.File]::WriteAllText($file.FullName, $new, $encoding)
            Write-Host "Fixed: $relative"
            $changed++
        }
        Write-Host "Updated $changed local file(s). Backups: $backupRoot"
    } else {
        Write-Host "Python is below 3.14; no local PySide6 pins changed."
    }

    Write-Host "Installing compatible build dependencies..."
    & $python -m pip install --disable-pip-version-check --upgrade -r "requirements-build.txt"
    if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed." }

    & $python -c "import sys, PySide6, PyInstaller; print(sys.version.split()[0], PySide6.__version__, PyInstaller.__version__)"
    if ($LASTEXITCODE -ne 0) { throw "Python build dependency import failed." }

    if ($Publish) {
        $script = Join-Path $PSScriptRoot "publish_all_release.ps1"
        if (-not (Test-Path $script -PathType Leaf)) {
            throw "Local publish_all_release.ps1 was not found; no release was published."
        }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -GitHubRepo $GitHubRepo
        if ($LASTEXITCODE -ne 0) { throw "Publication failed ($LASTEXITCODE)." }
    } elseif ($BuildOnly) {
        $allBuild = Join-Path $PSScriptRoot "build_all_release.ps1"
        if (Test-Path $allBuild -PathType Leaf) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $allBuild
        } else {
            Write-Warning "Local build_all_release.ps1 not found. Building DailyLog + Updater only."
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_release.ps1") -GitHubRepo $GitHubRepo
        }
        if ($LASTEXITCODE -ne 0) { throw "Build failed ($LASTEXITCODE)." }
    } else {
        Write-Host "Repair completed. No build or GitHub Release was published."
    }
}
finally {
    Pop-Location
}
