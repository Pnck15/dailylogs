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


function Restore-BuildReleaseFromGitHub {
    $filePath = Join-Path $PSScriptRoot "build_release.ps1"
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
        throw "build_release.ps1 does not exist in the project directory."
    }

    $existing = [System.IO.File]::ReadAllText($filePath)
    $conflictPattern = '(?m)^(<<<<<<<(?: .*)?|=======|>>>>>>>(?: .*)?)\s*$'
    if (-not [regex]::IsMatch($existing, $conflictPattern)) { return }

    Write-Warning "Detected unresolved Git conflict markers in build_release.ps1."
    $backupDir = Join-Path $PSScriptRoot (
        ".build_repair_backups\" + (Get-Date -Format "yyyyMMdd_HHmmss_fff")
    )
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $backupPath = Join-Path $backupDir "build_release.ps1"
    Copy-Item -LiteralPath $filePath -Destination $backupPath -Force
    Write-Host "Original conflicting file saved at: $backupPath"

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git CLI not found. Restore build_release.ps1 from origin/main manually."
    }
    & git -C $PSScriptRoot fetch --no-tags origin main
    if ($LASTEXITCODE -ne 0) {
        throw "Could not fetch origin/main; original build_release.ps1 was backed up."
    }

    # Restore only the affected tracked script (both index and worktree).
    # Do not touch untracked local notify/publish scripts.
    & git -C $PSScriptRoot restore --source=origin/main --staged --worktree -- build_release.ps1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not restore build_release.ps1 from origin/main."
    }

    $restored = [System.IO.File]::ReadAllText($filePath)
    if ([regex]::IsMatch($restored, $conflictPattern)) {
        throw "The restored build_release.ps1 still contains merge conflict markers."
    }
    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $filePath, [ref]$tokens, [ref]$parseErrors
    )
    if ($parseErrors.Count -gt 0) {
        throw "Restored build_release.ps1 has PowerShell parse errors."
    }
    Write-Host "Restored clean build_release.ps1 from origin/main."
}

Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Missing .venv\Scripts\python.exe. Create the project venv first."
    }

    # Repair the specific tracked script from the reviewed GitHub version.
    Restore-BuildReleaseFromGitHub

    $version = (& $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Cannot query Python version." }
    Write-Host "Project Python: $version"
    $parts = $version.Split('.')
    $isPython314 = ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 14)

    if ($isPython314) {
        Write-Host "Checking local build scripts for incompatible PySide6 pins..."
        # The local notifier build can read a different requirements file.
        # Recursively find build/dependency files, without traversing .venv
        # or any generated release files.
        $targets = @()
        $pending = New-Object 'System.Collections.Generic.Stack[string]'
        $pending.Push($PSScriptRoot)
        $skipDirs = @(
            ".venv", "venv", ".git", "build", "dist", "release",
            ".build_repair_backups", "__pycache__", "node_modules", ".idea"
        )
        while ($pending.Count -gt 0) {
            $folder = $pending.Pop()
            $targets += @(Get-ChildItem -LiteralPath $folder -File -ErrorAction Stop)
            foreach ($child in @(Get-ChildItem -LiteralPath $folder -Directory -ErrorAction Stop)) {
                if ($child.Name -in $skipDirs) { continue }
                $pending.Push($child.FullName)
            }
        }

        $legacyPin = '(?i)\bPySide6\s*==\s*6\.(?:[0-9]\.\d+(?:\.\d+)?|10\.0)\b'
        $backupRoot = Join-Path $PSScriptRoot (".build_repair_backups\" + (Get-Date -Format "yyyyMMdd_HHmmss"))
        $changed = 0
        foreach ($file in $targets) {
            $scriptFile = $file.Extension -in @(".ps1", ".cmd", ".bat")
            $dependencyFile = (
                $file.Extension -in @(".txt", ".in", ".toml", ".cfg", ".ini") -and
                $file.Name -match '(?i)requirements|dependenc|pyproject|pipfile|setup|tox'
            )
            $buildSpec = ($file.Extension -eq ".spec")
            if (-not ($scriptFile -or $dependencyFile -or $buildSpec)) { continue }
            if ($file.Name -eq "repair_build.ps1") { continue }

            $old = [System.IO.File]::ReadAllText($file.FullName)
            if ([regex]::IsMatch($old, '(?m)^<{7}(?: .*)?$')) {
                throw "Unresolved Git conflict in $($file.FullName). Resolve this file before building."
            }
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
            if ($utf16le) { $encoding = [System.Text.UnicodeEncoding]::new($false, $true) }
            elseif ($utf16be) { $encoding = [System.Text.UnicodeEncoding]::new($true, $true) }
            else { $encoding = [System.Text.UTF8Encoding]::new($utf8bom) }

            [System.IO.File]::WriteAllText($file.FullName, $new, $encoding)
            Write-Host "Fixed: $relative"
            $changed++
        }
        if ($changed -gt 0) {
            Write-Host "Updated $changed local file(s). Backups: $backupRoot"
        } else {
            Write-Host "No incompatible PySide6 pin found in local build files."
        }

        # Detect any remaining incompatible pins *before* invoking pip/build.
        # Otherwise a build may still read a second requirements file and fail.
        $remaining = @()
        foreach ($file in $targets) {
            $scriptFile = $file.Extension -in @(".ps1", ".cmd", ".bat")
            $dependencyFile = (
                $file.Extension -in @(".txt", ".in", ".toml", ".cfg", ".ini") -and
                $file.Name -match '(?i)requirements|dependenc|pyproject|pipfile|setup|tox'
            )
            if (-not ($scriptFile -or $dependencyFile -or $file.Extension -eq ".spec")) { continue }
            $content = [System.IO.File]::ReadAllText($file.FullName)
            if ([regex]::IsMatch($content, $legacyPin)) {
                $remaining += $file.FullName
            }
        }
        if ($remaining.Count -gt 0) {
            throw "Incompatible PySide6 pins still found: $($remaining -join ', ')"
        }
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
        $notifyBuilt = $false
        $buildStartUtc = (Get-Date).ToUniversalTime()
        if (Test-Path $allBuild -PathType Leaf) {
            Write-Host "Running local build_all_release.ps1 (includes notifier)..."
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $allBuild
            $notifyBuilt = $true
        } else {
            Write-Warning "Local build_all_release.ps1 not found. Building DailyLog + Updater only."
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_release.ps1") -GitHubRepo $GitHubRepo
        }
        if ($LASTEXITCODE -ne 0) { throw "Build failed ($LASTEXITCODE)." }
        if ($notifyBuilt) {
            $notifyExe = Join-Path $PSScriptRoot "release\DailyLogNotify.exe"
            if (-not (Test-Path -LiteralPath $notifyExe -PathType Leaf)) {
                throw "Notifier build did not create release\DailyLogNotify.exe."
            }
            $item = Get-Item -LiteralPath $notifyExe
            if ($item.LastWriteTimeUtc -lt $buildStartUtc.AddSeconds(-5)) {
                throw "release\DailyLogNotify.exe is stale; notifier was not rebuilt in this run."
            }
            Write-Host "Confirmed fresh DailyLogNotify.exe build."
        }
    } else {
        Write-Host "Repair completed. No build or GitHub Release was published."
    }
}
finally {
    Pop-Location
}
