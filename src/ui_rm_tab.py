from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.db import get_rm_config, set_rm_config


class RMTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        title = QLabel("TOTVS RM")
        title.setObjectName("TabTitle")
        subtitle = QLabel("Configuração de acesso ao banco de dados do RM")
        subtitle.setObjectName("TabSubtitle")

        form = QFrame()
        form.setObjectName("FormCard")
        form_layout = QFormLayout(form)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("192.168.0.10")

        self.db_input = QLineEdit()
        self.db_input.setPlaceholderText("RM")

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("usuario")

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("senha")
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)

        form_layout.addRow("Host (IP)", self.host_input)
        form_layout.addRow("BD", self.db_input)
        form_layout.addRow("Usuário", self.user_input)
        form_layout.addRow("Senha", self.pass_input)

        self.save_button = QPushButton("Salvar")
        self.save_button.clicked.connect(self.on_save)

        actions = QHBoxLayout()
        actions.addWidget(self.save_button)
        actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(form)
        layout.addLayout(actions)
        layout.addStretch(1)

        current = get_rm_config()
        if current:
            host, db_name, username, password = current
            self.host_input.setText(host)
            self.db_input.setText(db_name)
            self.user_input.setText(username)
            self.pass_input.setText(password)

    def on_save(self) -> None:
        host = self.host_input.text().strip()
        db_name = self.db_input.text().strip()
        username = self.user_input.text().strip()
        password = self.pass_input.text().strip()
        if not host or not db_name or not username or not password:
            return
        set_rm_config(host, db_name, username, password)
