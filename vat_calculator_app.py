"""Standalone VATCalculator.exe: shares the exact 3-tab DailyLog VAT calculator."""
import sys
from PySide6.QtWidgets import QApplication
from vat_calculator_ui import VATCalculatorWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = VATCalculatorWindow(standalone=True)
    if "--smoke-test" in sys.argv:
        assert win.tabs.count() == 3
        assert win.windowTitle() == "VAT Calculator 增值税计算器"
        assert win.menu_button.isEnabled()
        raise SystemExit(0)
    win.show()
    sys.exit(app.exec())
