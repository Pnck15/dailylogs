"""Run the compiled updater against real binaries on the Windows runner."""
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
    target = Path(folder) / "DailyLogNotify.exe"
    source = root / "release" / "DailyLogNotify.exe"
    shutil.copy2(source, target)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        result = subprocess.run([
            str(root / "release" / "DailyLogUpdater.exe"), str(parent.pid), str(target),
            str(source), digest, "--smoke-test"
        ], timeout=120)
        assert parent.poll() is not None, "Updater did not wait for its parent"
    finally:
        parent.wait(timeout=10)
    assert result.returncode == 0, f"Updater exit code: {result.returncode}"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert target.with_suffix(".old.exe").exists()
    print("Compiled updater installed the verified executable and restarted it.")
