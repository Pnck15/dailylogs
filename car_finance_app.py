"""Independent Windows FinanceCalculator.exe entrypoint."""
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from car_finance_ui import CarFinanceCalculator, CAR_CALCULATOR_VERSION

if __name__ == "__main__":
    app = QApplication(sys.argv)
    if "--smoke-test" in sys.argv:
        win = CarFinanceCalculator(standalone=True)
        assert win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert win.tabs.count() >= 1
        assert win.selected_down == 20
        raise SystemExit(0)
    window = CarFinanceCalculator(standalone=True)
    window.show()
    sys.exit(app.exec())
