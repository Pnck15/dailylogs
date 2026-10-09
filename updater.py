import ctypes
import hashlib
import os
import logging
import re
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
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid))
    if not handle:
        return
    try:
        result = kernel.WaitForSingleObject(handle, int(timeout * 1000))
        if result != 0:
            raise TimeoutError("Parent process did not exit; keeping the running app")
    finally:
        kernel.CloseHandle(handle)


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def install_update(parent_pid, target, url, expected_sha256="", relaunch_args=()):
    target = Path(target).resolve()
    expected_sha256 = expected_sha256.strip().lower()
    # Never replace a file which the receiver still has open.
    try:
        wait_for_process(parent_pid)
    except TimeoutError:
        logging.exception("Parent process is still running")
        return 7

    temp_dir = None
    backup = target.with_suffix(".old.exe")
    replaced = False
    launched = False
    result = 5
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix=".DailyLogUpdate_", dir=target.parent))
        new_file = temp_dir / target.name
        if url.startswith(("http://", "https://")):
            # Compatibility with already installed Notify and the main DailyLog app.
            with requests.get(url, stream=True, timeout=(10, 180),
                              headers={"User-Agent": "DailyLog-Updater"}) as response:
                response.raise_for_status()
                with new_file.open("wb") as out:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            out.write(chunk)
        else:
            # New Notify versions download while the receiver is still running.
            if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
                raise ValueError("Prepared updates require SHA256")
            shutil.copy2(Path(url).resolve(), new_file)
        if new_file.stat().st_size < 100 * 1024:
            raise ValueError("Downloaded executable is too small")
        with new_file.open("rb") as file:
            if file.read(2) != b"MZ":
                raise ValueError("Downloaded file is not a Windows executable")
        if expected_sha256 and sha256_file(new_file) != expected_sha256:
            raise ValueError("Update SHA256 does not match")
        if target.exists():
            shutil.copy2(target, backup)
        last_error = None
        for _ in range(20):
            try:
                os.replace(new_file, target)
                last_error = None
                replaced = True
                break
            except OSError as error:
                last_error = error
                time.sleep(0.5)
        if last_error:
            raise last_error
        subprocess.Popen([str(target), *relaunch_args], close_fds=True)
        launched = True
        result = 0
    except Exception:
        logging.exception("Update failed; restarting the previous version")
        if replaced and backup.exists():
            try:
                shutil.copy2(backup, target)
            except Exception:
                logging.exception("Could not restore the previous executable")
    finally:
        if not launched and target.exists():
            try:
                subprocess.Popen([str(target), *relaunch_args], close_fds=True)
            except Exception:
                logging.exception("Could not restart the receiver")
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def main():
    if len(sys.argv) < 4:
        return 2
    log_dir = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir())) / "DailyLogNotify"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=log_dir / "updater.log", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        pass
    return install_update(int(sys.argv[1]), sys.argv[2], sys.argv[3].strip(),
                          sys.argv[4] if len(sys.argv) >= 5 else "",
                          sys.argv[5:])


if __name__ == "__main__":
    raise SystemExit(main())
