import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


def wait_for_process(pid, timeout=60):
    if os.name != "nt":
        return
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid))
    if not handle:
        return
    try:
        ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def main():
    if len(sys.argv) < 4:
        return 2

    parent_pid = int(sys.argv[1])
    target = Path(sys.argv[2]).resolve()
    url = sys.argv[3].strip()
    expected_sha256 = sys.argv[4].strip().lower() if len(sys.argv) >= 5 else ""
    relaunch_args = sys.argv[5:] if len(sys.argv) >= 6 else []

    wait_for_process(parent_pid)
    if not url.startswith(("http://", "https://")):
        return 3

    temp_dir = Path(tempfile.mkdtemp(prefix="DailyLogUpdate_"))
    new_file = temp_dir / target.name
    backup = target.with_suffix(".old.exe")

    try:
        with requests.get(
            url,
            stream=True,
            timeout=(10, 180),
            headers={"User-Agent": "DailyLog-Updater"},
        ) as response:
            response.raise_for_status()
            with new_file.open("wb") as out:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        out.write(chunk)

        if new_file.stat().st_size < 100 * 1024:
            return 4

        if expected_sha256 and sha256_file(new_file) != expected_sha256:
            return 6

        if target.exists():
            shutil.copy2(target, backup)

        last_error = None
        for _ in range(20):
            try:
                os.replace(new_file, target)
                last_error = None
                break
            except OSError as error:
                last_error = error
                time.sleep(0.5)

        if last_error is not None:
            raise last_error

        subprocess.Popen(
            [str(target), *relaunch_args],
            close_fds=True,
        )
        return 0
    except Exception:
        if backup.exists() and not target.exists():
            shutil.copy2(backup, target)
        return 5
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
