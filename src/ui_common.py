from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout, QComboBox

from core.db import get_config, set_config


class ConfigCard(QFrame):
    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConfigCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        title = QLabel("Configuração local")
        title.setObjectName("CardTitle")

        subtitle = QLabel("Armazena preferências do aplicativo")
        subtitle.setObjectName("CardSubtitle")

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText(
            "Nome da instância (ex.: produção, homologação)"
        )

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


class LazyComboBox(QComboBox):
    def __init__(self, loader=None) -> None:
        super().__init__()
        self._loader = loader
        self._loaded = False

    def set_loader(self, loader) -> None:
        self._loader = loader

    def reset_loaded(self) -> None:
        self._loaded = False

    def showPopup(self) -> None:
        if self._loader and not self._loaded:
            self._loader()
            self._loaded = True
        super().showPopup()
