# DailyLog: Windows Build / Python 3.14

## Fixed in GitHub

- \`requirements.txt\` now requires \`PySide6>=6.10.1,<7\` because 6.8.3 cannot be installed on Python 3.14.
- \`requirements-build.txt\` installs runtime dependencies and a Python 3.14-compatible PyInstaller.
- \`build_release.ps1\` stops immediately if dependency installation or either EXE build fails.
- \`repair_build.ps1\` detects old PySide6 pins in *local* scripts, backs them up, and replaces them with 6.10.2 when the project venv is Python 3.14+.

## Run on the Windows build PC

In PowerShell:

\`\`\`powershell
cd D:\mini_daily_log
git pull origin main
powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_build.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_build.ps1 -BuildOnly
\`\`\`

This calls the **existing local** \`build_all_release.ps1\` (if present), which should produce
\`release\DailyLog.exe\`, \`release\DailyLogUpdater.exe\`, and
\`release\DailyLogNotify.exe\`. If that local script is not present, only
\`DailyLog.exe\` and \`DailyLogUpdater.exe\` are built, with a warning.

After confirming the binaries and increasing \`APP_VERSION\` for a *new* release:

\`\`\`powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_build.ps1 -Publish -GitHubRepo "Pnck15/dailylogs"
\`\`\`

**Important:** The original \`build_notify.ps1\`, \`build_all_release.ps1\`, and
\`publish_all_release.ps1\` reported in the build log exist on the Windows PC
but were **not in this GitHub repository**. They cannot be audited or
replaced on that PC from GitHub alone. The repair script modifies only those
local scripts it finds, after backing them up.

**If \`git pull\` reports an untracked-file conflict for \`repair_build.ps1\`:**
move the old local copy outside the repository, then pull again. Do not discard
local scripts or app configuration.

**Build is not Publish.** GitHub source commits alone do not update existing
Windows installations. Installing a new version on other PCs requires a
successful GitHub Release with matching \`version.json\` and binaries.

## Diagnostics

Confirm the active venv, not the global Python:

\`\`\`powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip show PySide6 PyInstaller
\`\`\`

If \`DailyLogNotify.exe\` is still absent, inspect the output from the local
\`build_notify.ps1\` after the dependency repair. The notifier entrypoint/spec
must be valid before a notifier EXE can be generated.
