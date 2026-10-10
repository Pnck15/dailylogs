$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create build environment." }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements-notify-build.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

function Get-EnvValue([string]$Name) {
    if (-not (Test-Path ".env")) { return "" }
    $line = Get-Content ".env" | Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } | Select-Object -First 1
    if (-not $line) { return "" }
    return ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
}
$supabaseUrl = Get-EnvValue "SUPABASE_URL"
$supabaseKey = Get-EnvValue "SUPABASE_PUBLISHABLE_KEY"
if (-not $supabaseUrl -or -not $supabaseKey) {
    # Public client configuration only; never a service-role key.
    $config = Get-Content "notify_build_config.json" -Raw | ConvertFrom-Json
    $supabaseUrl = $config.SUPABASE_URL
    $supabaseKey = $config.SUPABASE_PUBLISHABLE_KEY
}
if (-not $supabaseUrl -or -not $supabaseKey) { throw "Supabase client configuration missing." }
$notifyEnv = "SUPABASE_URL=$supabaseUrl`nSUPABASE_PUBLISHABLE_KEY=$supabaseKey`n"
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "notify.env"), $notifyEnv, (New-Object System.Text.UTF8Encoding($false)))
try {
    foreach ($spec in @("DailyLogNotify.spec", "updater.spec")) {
        & .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm $spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $spec" }
    }
    New-Item -ItemType Directory -Force -Path "release" | Out-Null
    Copy-Item "dist\DailyLogNotify.exe" "release\DailyLogNotify.exe" -Force
    Copy-Item "dist\DailyLogUpdater.exe" "release\DailyLogUpdater.exe" -Force
}
finally {
    if (Test-Path "notify.env") { Remove-Item "notify.env" -Force }
}
Write-Host "Build complete: release\DailyLogNotify.exe and release\DailyLogUpdater.exe"
