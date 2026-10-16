"""Offline Windows Toast security and registration smoke.

The mocked Python test never shows real notifications. On GitHub Actions
Windows, only the Start-menu AUMID setup is executed; actual toast display
requires an interactive Windows desktop and must be checked on a user's PC.
"""
import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notify_windows_toast import (
    APP_USER_MODEL_ID, native_windows_toast, toast_script_path,
    check_windows_notification_registration,
)


def test_command_arguments_are_safe():
    with tempfile.TemporaryDirectory() as root:
        exe = Path(root) / "DailyLogNotify.exe"
        exe.write_bytes(b"MZ")
        script = Path(root) / "notify_windows_toast.ps1"
        script.write_text("# synthetic test")
        original_title = 'แก้ไขข้อมูล "a"; $(echo INJECT) 漢字'
        original_body = "VIN: LMH123\nข้อความ: value & <value>"
        observed = []

        def fake_subprocess(cmd, **kwargs):
            observed.append((cmd, kwargs))
            return SimpleNamespace(returncode=0, stdout=b"TOAST_SUBMITTED\r\n", stderr=b"")

        with patch("notify_windows_toast.subprocess.run", side_effect=fake_subprocess):
            assert native_windows_toast(
                original_title, original_body,
                exe_path=exe, script_path=script, system="win32"
            ) is True

        cmd, kwargs = observed[0]
        assert cmd[0].lower() == "powershell.exe"
        assert kwargs["timeout"] <= 25
        assert "-File" in cmd
        assert "-Command" not in cmd, "Untrusted data must never execute as PowerShell"
        assert original_title not in " ".join(cmd)
        assert original_body not in " ".join(cmd)
        assert cmd[cmd.index("-AppId") + 1] == APP_USER_MODEL_ID
        title = base64.b64decode(cmd[cmd.index("-TitleBase64") + 1]).decode("utf-8")
        body = base64.b64decode(cmd[cmd.index("-BodyBase64") + 1]).decode("utf-8")
        assert title == original_title
        assert body == original_body

        def fail(*args, **kwargs):
            return SimpleNamespace(
                returncode=1, stdout=b"",
                stderr=b"DAILYLOG_TOAST_ERROR: Notifications disabled",
            )
        with patch("notify_windows_toast.subprocess.run", side_effect=fail):
            try:
                native_windows_toast(
                    "test", "body", exe_path=exe, script_path=script,
                    system="win32"
                )
            except RuntimeError as exc:
                assert "Notifications disabled" in str(exc)
            else:
                raise AssertionError("Native Windows Toast failure must be observable")

        with patch("notify_windows_toast.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("powershell", 2)):
            try:
                native_windows_toast(
                    "test", "body", exe_path=exe, script_path=script,
                    system="win32"
                )
            except subprocess.TimeoutExpired:
                pass
            else:
                raise AssertionError("Timeout must propagate to fallback")

        # Repair mode uses script-file args only: it never writes Windows
        # notification permissions or runs source/event text as code.
        observed = []
        def diagnose_stub(cmd, **kwargs):
            observed.append((cmd, kwargs))
            return SimpleNamespace(
                returncode=0,
                stdout=b"SHORTCUT_REPAIRED\r\nTOAST_SETTING:DisabledForApplication\r\n",
                stderr=b"",
            )
        with patch("notify_windows_toast.subprocess.run", side_effect=diagnose_stub):
            setting = check_windows_notification_registration(
                repair=True, exe_path=exe, script_path=script, system="win32"
            )
            assert setting == "DisabledForApplication"
        cmd, kwargs = observed[0]
        assert "-RepairShortcut" in cmd
        assert "-Command" not in cmd
        assert kwargs["timeout"] >= 40
        assert original_body not in " ".join(cmd)
        with patch(
            "notify_windows_toast.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout=b"TOAST_SETTING:Enabled\r\n",
                stderr=b"",
            ),
        ):
            assert check_windows_notification_registration(
                repair=False, exe_path=exe, script_path=script, system="win32"
            ) == "Enabled"

    power_shell = toast_script_path().read_text(encoding="utf-8")
    for setting_name in (
        "DisabledForApplication", "DisabledForUser",
        "DisabledByGroupPolicy", "DisabledByManifest",
    ):
        assert setting_name in power_shell
    assert "SHORTCUT_REPAIRED" in power_shell
    assert "TOAST_SETTING:" in power_shell
    assert "Set-ItemProperty" not in power_shell
    assert "New-ItemProperty" not in power_shell
    assert toast_script_path().is_file(), "Bundled native toast script must exist in checkout"


def test_shortcut_registration_windows_ci():
    if os.name != "nt" or os.environ.get("CI", "").lower() != "true":
        return
    script = toast_script_path()
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script),
        "-ExePath", sys.executable,
        "-RegisterOnly",
    ]
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=75, check=False,
    )
    assert proc.returncode == 0, (
        "Start-menu AppUserModelID registration failed:\n"
        + proc.stderr.decode("utf-8", errors="replace")[:5000]
    )
    assert b"REGISTERED" in proc.stdout
    # Exercise actual shortcut recreation on the Windows CI host without
    # attempting an interactive toast or reading user's Windows preferences.
    repair = subprocess.run(
        cmd + ["-RepairShortcut"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=75, check=False,
    )
    assert repair.returncode == 0, (
        "Safe Windows shortcut re-registration failed:\n"
        + repair.stderr.decode("utf-8", errors="replace")[:5000]
    )
    assert b"REGISTERED" in repair.stdout
    link = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "DailyLogNotify.lnk"
    assert link.is_file(), "Native Toast must have Start-menu shortcut"


if __name__ == "__main__":
    test_command_arguments_are_safe()
    test_shortcut_registration_windows_ci()
    print("PASS: Base64 sanitization, native failure/timeout propagation and Windows AUMID shortcut.")
