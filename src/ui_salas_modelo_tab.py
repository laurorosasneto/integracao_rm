from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.db import (
    create_sala_modelo,
    delete_sala_modelo,
    list_platforms_for_select,
    list_salas_modelo,
    update_sala_modelo,
)


class SalasModeloTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.selected_id: int | None = None

        title = QLabel("Salas Modelo")
        title.setObjectName("TabTitle")
        subtitle = QLabel(
            "Cadastre salas modelo (por plataforma) para facilitar o mapeamento/execução"
        )
        subtitle.setObjectName("TabSubtitle")

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("DataTable")
        self.table.setHorizontalHeaderLabels(
            ["Plataforma", "Nome", "ID Moodle", "Filtro Extra"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_table_select)

        form = QFrame()
        form.setObjectName("FormCard")
        form_layout = QFormLayout(form)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.platform_select = QComboBox()
        self.platform_select.setObjectName("Select")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ex.: Sala 101")

        self.moodle_id_input = QLineEdit()
        self.moodle_id_input.setPlaceholderText("Ex.: 123")

        self.extra_filter_input = QPlainTextEdit()
        # Reutiliza o estilo de campos longos já existente no app
        self.extra_filter_input.setObjectName("SqlField")
        self.extra_filter_input.setPlaceholderText(
            "Filtro extra (texto longo). Ex.: CODCOLIGADA IN (1,2) AND TURMA LIKE '%A%'."
        )

        form_layout.addRow("Plataforma", self.platform_select)
        form_layout.addRow("Nome", self.name_input)
        form_layout.addRow("ID Moodle", self.moodle_id_input)
        form_layout.addRow("Filtro Extra", self.extra_filter_input)

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

        form_block = QVBoxLayout()
        form_block.addWidget(form)
        form_block.addLayout(actions)

        self._form = form
        self._actions = actions

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addLayout(form_block)
        content_layout.addSpacing(12)
        content_layout.addWidget(self.table)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("TabScroll")
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

        self.load_platforms()
        self.refresh_table()
        QTimer.singleShot(0, self._sync_table_height)

    def load_platforms(self) -> None:
        self.platform_select.blockSignals(True)
        self.platform_select.clear()
        for platform_id, name in list_platforms_for_select():
            self.platform_select.addItem(name, platform_id)
        self.platform_select.blockSignals(False)

    def refresh_table(self) -> None:
        rows = list_salas_modelo()
        self.table.setRowCount(0)
        for (
            sala_id,
            _created_at,
            _platform_id,
            platform_name,
            name,
            moodle_id,
            extra_filter,
            _updated_at,
        ) in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(platform_name or ""))
            self.table.setItem(row, 1, QTableWidgetItem(name or ""))
            self.table.setItem(row, 2, QTableWidgetItem(moodle_id or ""))
            preview = (extra_filter or "").strip().replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:120] + "..."
            self.table.setItem(row, 3, QTableWidgetItem(preview))

            self.table.setRowHeight(row, 36)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, int(sala_id))

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _sync_table_height(self) -> None:
        target = self._form.sizeHint().height() + self._actions.sizeHint().height()
        self.table.setFixedHeight(max(240, target))

    def on_new(self) -> None:
        self.selected_id = None
        self.name_input.clear()
        self.moodle_id_input.clear()
        self.extra_filter_input.setPlainText("")
        self.table.clearSelection()
        if self.platform_select.count() > 0:
            self.platform_select.setCurrentIndex(0)

    def on_table_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return

        sala_id = items[0].data(Qt.ItemDataRole.UserRole)
        if sala_id is None:
            return
        self.selected_id = int(sala_id)

        for (
            sid,
            _created_at,
            platform_id,
            _platform_name,
            name,
            moodle_id,
            extra_filter,
            _updated_at,
        ) in list_salas_modelo():
            if int(sid) != self.selected_id:
                continue

            idx = self.platform_select.findData(int(platform_id))
            if idx >= 0:
                self.platform_select.setCurrentIndex(idx)
            self.name_input.setText(name or "")
            self.moodle_id_input.setText(moodle_id or "")
            self.extra_filter_input.setPlainText(extra_filter or "")
            break

    def on_save(self) -> None:
        platform_id = self.platform_select.currentData()
        if platform_id is None:
            QMessageBox.warning(self, "Plataforma obrigatória", "Selecione uma plataforma.")
            return

        name = self.name_input.text().strip()
        moodle_id = self.moodle_id_input.text().strip()
        extra_filter = self.extra_filter_input.toPlainText().strip()

        if not name or not moodle_id:
            QMessageBox.warning(
                self,
                "Campos obrigatórios",
                "Preencha Nome e ID Moodle para salvar.",
            )
            return

        if self.selected_id is None:
            create_sala_modelo(int(platform_id), name, moodle_id, extra_filter)
        else:
            update_sala_modelo(self.selected_id, int(platform_id), name, moodle_id, extra_filter)

        self.refresh_table()
        QMessageBox.information(self, "Salvo", "Sala Modelo salva com sucesso.")

    def on_delete(self) -> None:
        if self.selected_id is None:
            return
        delete_sala_modelo(self.selected_id)
        self.on_new()
        self.refresh_table()