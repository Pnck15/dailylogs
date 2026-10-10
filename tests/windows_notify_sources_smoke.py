"""Offline Notify Source catalog refresh: live choices without restarting EXE."""
import os
import sys
import tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QScrollArea

from dailylog_notify import SourceSelectionDialog
from notify_receiver import SOURCE_REFRESH_INTERVAL_MS


def test_catalog(app):
    assert SOURCE_REFRESH_INTERVAL_MS == 60_000
    with tempfile.TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "sources.ini"),
            QSettings.Format.IniFormat,
        )
        settings.setValue("sources/selected", "sa_sathorn")
        original = [
            {"key": "sa_sathorn", "label": "SA Sathorn"}
        ]
        new_catalog = [
            {"key": "sa_sathorn", "label": "SA Sathorn"},
            {"key": "main_test", "label": "Booking Changes"},
        ]
        dialog = SourceSelectionDialog(settings, original)
        assert dialog.findChild(QScrollArea) is not None
        assert dialog.selected_keys() == ["sa_sathorn"]
        assert dialog.checkboxes.get("main_test") is None

        # A live source_list_changed event must redraw the OPEN dialog.
        dialog.update_options(new_catalog)
        assert dialog.checkboxes.get("main_test") is not None
        assert dialog.selected_keys() == ["sa_sathorn"]
        dialog.checkboxes["main_test"].setChecked(True)
        # Refresh must preserve unsaved employee selection.
        dialog.update_options(new_catalog)
        assert set(dialog.selected_keys()) == {"sa_sathorn", "main_test"}

        dialog._save()
        assert str(settings.value("sources/selected")) == "sa_sathorn,main_test"
        assert dialog.result() == dialog.DialogCode.Accepted
        dialog.close()
        settings.sync()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    test_catalog(app)
    print("PASS: one-minute source discovery, scrollable live catalog, preserved employee selections.")
