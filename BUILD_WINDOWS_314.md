# DailyLog: Windows Build / Python 3.14

## Fixed in GitHub

- `requirements.txt` now requires `PySide6>=6.10.1,<7` because 6.8.3 cannot be installed on Python 3.14.
- `requirements-build.txt` installs runtime dependencies and a Python 3.14-compatible PyInstaller.
- `build_release.ps1` stops immediately if dependency installation or either EXE build fails.
- `repair_build.ps1` detects old PySide6 pins in *local* scripts, backs them up, and replaces them with 6.10.2 when the project venv is Python 3.14+.

## Run on the Windows build PC

In PowerShell:

```powershell
cd D:\mini_daily_log
git pull origin main
powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_build.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_build.ps1 -BuildOnly
```

This calls the **existing local** `build_all_release.ps1` (if present), which should produce
`release\DailyLog.exe`, `release\DailyLogUpdater.exe`, and
`release\DailyLogNotify.exe`. If that local script is not present, only
`DailyLog.exe` and `DailyLogUpdater.exe` are built, with a warning.

After confirming the binaries and increasing `APP_VERSION` for a *new* release:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_build.ps1 -Publish -GitHubRepo "Pnck15/dailylogs"
```

**Important:** The original `build_notify.ps1`, `build_all_release.ps1`, and
`publish_all_release.ps1` reported in the build log exist on the Windows PC
but were **not in this GitHub repository**. They cannot be audited or
replaced on that PC from GitHub alone. The repair script modifies only those
local scripts it finds, after backing them up.

**If `git pull` reports an untracked-file conflict for `repair_build.ps1`:**
move the old local copy outside the repository, then pull again. Do not discard
local scripts or app configuration.

**Build is not Publish.** GitHub source commits alone do not update existing
Windows installations. Installing a new version on other PCs requires a
successful GitHub Release with matching `version.json` and binaries.

## The specific DailyLogNotify.exe error

If the Windows log reports `D:\mini_daily_log\build_notify.ps1:9` with
`No matching distribution found for PySide6==6.8.3`, then the *local*
notifier build is still installing an incompatible legacy dependency.

**Do not rerun `publish_all_release.ps1` directly.** Pull the latest
repair script from GitHub and invoke it instead:

```powershell
cd D:\mini_daily_log
git pull --ff-only origin main
powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_build.ps1 -BuildOnly
```

The repair script now scans project build/requirements files in subdirectories
(excluding virtual environments, generated outputs, and backups). It saves
originals under `.build_repair_backups`, replaces incompatible PySide6 exact
pins, and confirms that `release\DailyLogNotify.exe` was freshly built.
It also checks the Python version of `.venv`, not the global interpreter.

If `git pull` cannot run because an old, untracked `repair_build.ps1`
already exists, **back up that local copy** and then pull again. Do not
discard the local `build_notify.ps1` or `publish_all_release.ps1`:
they are currently only available on your build PC.

No source-only GitHub commit can directly edit files inside `D:\mini_daily_log`
until you synchronize the local checkout. No release has been published by
these fixes.

## PowerShell parse error: `<<<<<<< HEAD` in `build_release.ps1`

This is an unresolved **local Git merge conflict**, not a PyInstaller/PySide6 error.
The clean `build_release.ps1` on GitHub main contains no conflict markers.

When `git pull` is blocked by an unfinished merge, do **not** run
`git reset --hard` or delete project files. On the Windows build PC:

```powershell
cd D:\mini_daily_log

# Fetch the clean GitHub version; this does not merge.
git fetch origin main

# Save the two local scripts first.
New-Item -ItemType Directory -Force .\.build_repair_backups | Out-Null
Copy-Item .\build_release.ps1 .\.build_repair_backups\build_release.before_restore.ps1 -Force
Copy-Item .\repair_build.ps1 .\.build_repair_backups\repair_build.before_restore.ps1 -Force

# Replace only the tracked Build scripts with verified origin/main copies.
git restore --source=origin/main --staged --worktree -- build_release.ps1 repair_build.ps1

# Show any other unresolved merge files.
git diff --name-only --diff-filter=U

# Run normal local build, including the notifier.
powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_build.ps1 -BuildOnly
```

If `git diff --name-only --diff-filter=U` lists other paths, resolve those
separately before committing or pulling again. Local-only `build_notify.ps1`,
`build_all_release.ps1`, and `publish_all_release.ps1` remain untouched.
Do not publish a Release until the build passes and the application version
has been increased.
## Diagnostics

Confirm the active venv, not the global Python:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip show PySide6 PyInstaller
```

If `DailyLogNotify.exe` is still absent, inspect the output from the local
`build_notify.ps1` after the dependency repair. The notifier entrypoint/spec
must be valid before a notifier EXE can be generated.
