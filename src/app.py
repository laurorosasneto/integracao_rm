from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.db import (
    create_platform,
    delete_platform,
    get_config,
    list_platforms,
    set_config,
    update_platform,
)


class ConfigCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConfigCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        title = QLabel("Configuração local")
        title.setObjectName("CardTitle")

        subtitle = QLabel("Armazena preferências do aplicativo")
        subtitle.setObjectName("CardSubtitle")

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Nome da instância (ex.: produção, homologação)")

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


class PlatformsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.selected_id: int | None = None

        title = QLabel("Plataformas")
        title.setObjectName("TabTitle")
        subtitle = QLabel("Gerencie plataformas de integração com URL e Token")
        subtitle.setObjectName("TabSubtitle")

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("DataTable")
        self.table.setHorizontalHeaderLabels(["Plataforma", "URL", "Token"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_table_select)

        form = QFrame()
        form.setObjectName("FormCard")
        form_layout = QFormLayout(form)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Moodle Produção")

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://moodle.exemplo.com")

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Token de integração")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)

        form_layout.addRow("Plataforma", self.name_input)
        form_layout.addRow("URL", self.url_input)
        form_layout.addRow("Token", self.token_input)

        self.new_button = QPushButton("Novo")
        self.save_button = QPushButton("Salvar")
        self.delete_button = QPushButton("Excluir")

        self.new_button.clicked.connect(self.on_new)
        self.save_button.clicked.connect(self.on_save)
        self.delete_button.clicked.connect(self.on_delete)

        actions = QHBoxLayout()
        actions.addWidget(self.new_button)
        actions.addWidget(self.save_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(form)
        right.addLayout(actions)
        right.addStretch(1)

        body = QHBoxLayout()
        body.addWidget(self.table, 2)
        body.addLayout(right, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(body)

        self.refresh_table()

    def refresh_table(self) -> None:
        rows = list_platforms()
        self.table.setRowCount(0)
        for platform_id, name, url, token in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(url))
            masked = "*" * 8 if token else ""
            self.table.setItem(row, 2, QTableWidgetItem(masked))
            self.table.setRowHeight(row, 36)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, platform_id)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def on_table_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        platform_id = items[0].data(Qt.ItemDataRole.UserRole)
        if platform_id is None:
            return

        self.selected_id = int(platform_id)
        for pid, name, url, token in list_platforms():
            if pid == self.selected_id:
                self.name_input.setText(name)
                self.url_input.setText(url)
                self.token_input.setText(token)
                break

    def on_new(self) -> None:
        self.selected_id = None
        self.name_input.clear()
        self.url_input.clear()
        self.token_input.clear()
        self.table.clearSelection()

    def on_save(self) -> None:
        name = self.name_input.text().strip()
        url = self.url_input.text().strip()
        token = self.token_input.text().strip()
        if not name or not url or not token:
            return
        if self.selected_id is None:
            create_platform(name, url, token)
        else:
            update_platform(self.selected_id, name, url, token)
        self.refresh_table()

    def on_delete(self) -> None:
        if self.selected_id is None:
            return
        delete_platform(self.selected_id)
        self.on_new()
        self.refresh_table()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Integracao RM <-> Moodle")
        self.resize(960, 640)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        header = QLabel("Integração RM Totvs <-> Moodle")
        header.setObjectName("Header")
        header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        tabs = QTabWidget()
        tabs.setObjectName("MainTabs")
        tabs.addTab(PlatformsTab(), "Plataformas")

        layout = QVBoxLayout(root)
        layout.addWidget(header)
        layout.addWidget(tabs)


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
        #MainTabs::pane {
            border: none;
            margin: 0 16px 16px 16px;
        }
        #MainTabs QTabBar::tab {
            background: #e5e7eb;
            color: #374151;
            border: none;
            padding: 10px 16px;
            margin-right: 6px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }
        #MainTabs QTabBar::tab:selected {
            background: #111827;
            color: #ffffff;
        }
        #TabTitle {
            font-size: 20px;
            font-weight: 600;
            color: #111827;
            padding: 8px 16px 0 16px;
        }
        #TabSubtitle {
            color: #6b7280;
            padding: 0 16px 12px 16px;
        }
        #FormCard {
            background: white;
            border-radius: 14px;
            padding: 16px;
        }
        #DataTable {
            background: white;
            border-radius: 14px;
            gridline-color: #e5e7eb;
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
