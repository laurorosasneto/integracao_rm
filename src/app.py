from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from ui_main_window import MainWindow
from ui_styles import apply_styles


def main() -> None:
    app = QApplication([])
    apply_styles(app)

    window = MainWindow()
    window.show()

    app.exec()


if __name__ == "__main__":
    main()
