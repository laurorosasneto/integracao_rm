from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.db import get_config, set_config


class ConfigCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConfigCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        title = QLabel("Configura??o local")
        title.setObjectName("CardTitle")

        subtitle = QLabel("Armazena prefer?ncias e conex?es do aplicativo")
        subtitle.setObjectName("CardSubtitle")

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Nome da inst?ncia (ex.: producao, homologacao)")

        self.save_button = QPushButton("Salvar")
        self.save_button.clicked.connect(self.on_save)

        row = QHBoxLayout()
        row.addWidget(self.path_input)
        row.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(row)
        layout.addStretch(1)

        current = get_config("instance_name")
        if current:
            self.path_input.setText(current)

    def on_save(self) -> None:
        value = self.path_input.text().strip()
        if value:
            set_config("instance_name", value)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Integracao RM <-> Moodle")
        self.resize(960, 640)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        header = QLabel("Integra??o RM Totvs ? Moodle")
        header.setObjectName("Header")
        header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        card = ConfigCard()

        layout = QVBoxLayout(root)
        layout.addWidget(header)
        layout.addWidget(card)
        layout.addStretch(1)


def apply_styles(app: QApplication) -> None:
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(
        """
        #Root {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f5f7fb, stop:1 #e9eef5);
        }
        #Header {
            font-size: 26px;
            font-weight: 700;
            color: #1f2937;
            padding: 24px 24px 8px 24px;
        }
        #ConfigCard {
            background: white;
            border-radius: 14px;
            padding: 20px;
            margin: 0 24px 24px 24px;
        }
        #CardTitle {
            font-size: 18px;
            font-weight: 600;
            color: #111827;
        }
        #CardSubtitle {
            color: #6b7280;
            margin-bottom: 12px;
        }
        QLineEdit {
            border: 1px solid #d1d5db;
            border-radius: 8px;
            padding: 8px 10px;
            background: #f9fafb;
        }
        QLineEdit:focus {
            border: 1px solid #3b82f6;
            background: #ffffff;
        }
        QPushButton {
            background: #1f2937;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
        }
        QPushButton:hover {
            background: #111827;
        }
        QPushButton:pressed {
            background: #0f172a;
        }
        """
    )


def main() -> None:
    app = QApplication([])
    apply_styles(app)

    window = MainWindow()
    window.show()

    app.exec()


if __name__ == "__main__":
    main()
