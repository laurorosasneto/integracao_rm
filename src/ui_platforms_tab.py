from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.db import (
    create_platform,
    delete_platform,
    get_rm_config,
    get_rm_queries,
    list_platforms,
    update_platform,
)


class PlatformsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.selected_id: int | None = None

        title = QLabel("Plataformas")
        title.setObjectName("TabTitle")
        subtitle = QLabel("Gerencie plataformas de integração com URL e Token")
        subtitle.setObjectName("TabSubtitle")

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("DataTable")
        self.table.setHorizontalHeaderLabels(["Plataforma", "URL", "Token", "Coligadas"])
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

        self.coligadas_list = QListWidget()
        self.coligadas_list.setObjectName("Select")
        self.coligadas_list.itemChanged.connect(self.on_coligadas_changed)

        self.coligadas_summary = QLineEdit()
        self.coligadas_summary.setReadOnly(True)
        self.coligadas_summary.setPlaceholderText("Selecione uma ou mais coligadas")

        form_layout.addRow("Coligadas", self.coligadas_list)
        form_layout.addRow("Selecionadas", self.coligadas_summary)

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

        self._platform_form = form
        self._platform_actions = actions

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

        self.load_coligadas()
        self.refresh_table()
        QTimer.singleShot(0, self._sync_table_height)

    def refresh_table(self) -> None:
        rows = list_platforms()
        self.table.setRowCount(0)
        for platform_id, name, url, token, coligadas in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(url))
            masked = "*" * 8 if token else ""
            self.table.setItem(row, 2, QTableWidgetItem(masked))
            self.table.setItem(
                row, 3, QTableWidgetItem(self.get_coligadas_labels_from_csv(coligadas or ""))
            )
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
        for pid, name, url, token, coligadas in list_platforms():
            if pid == self.selected_id:
                self.name_input.setText(name)
                self.url_input.setText(url)
                self.token_input.setText(token)
                self.set_coligadas_from_csv(coligadas or "")
                break

    def on_new(self) -> None:
        self.selected_id = None
        self.name_input.clear()
        self.url_input.clear()
        self.token_input.clear()
        self.table.clearSelection()
        self.set_coligadas_from_csv("")

    def on_save(self) -> None:
        name = self.name_input.text().strip()
        url = self.url_input.text().strip()
        token = self.token_input.text().strip()
        if not name or not url or not token:
            QMessageBox.warning(
                self,
                "Campos obrigatórios",
                "Preencha Plataforma, URL e Token para salvar.",
            )
            return
        coligadas = self.get_coligadas_csv()
        if self.selected_id is None:
            create_platform(name, url, token, coligadas)
        else:
            update_platform(self.selected_id, name, url, token, coligadas)
        self.refresh_table()
        QMessageBox.information(
            self,
            "Salvo",
            "Plataforma salva com sucesso.",
        )

    def on_delete(self) -> None:
        if self.selected_id is None:
            return
        delete_platform(self.selected_id)
        self.on_new()
        self.refresh_table()

    def _sync_table_height(self) -> None:
        target = self._platform_form.sizeHint().height() + self._platform_actions.sizeHint().height()
        self.table.setFixedHeight(max(240, target))

    def load_coligadas(self) -> None:
        self.coligadas_list.blockSignals(True)
        self.coligadas_list.clear()

        all_item = QListWidgetItem("Todos")
        all_item.setData(Qt.ItemDataRole.UserRole, "__ALL__")
        all_item.setCheckState(Qt.CheckState.Unchecked)
        self.coligadas_list.addItem(all_item)

        queries = get_rm_queries()
        config = get_rm_config()
        sql = queries.get("coligadas", "").strip() if queries else ""

        if not sql or not config:
            self.coligadas_list.blockSignals(False)
            return

        host, db_name, username, password = config
        try:
            import pyodbc  # type: ignore
        except Exception as exc:  # pragma: no cover
            QMessageBox.warning(
                self,
                "Driver não disponível",
                f"Erro ao carregar pyodbc: {exc}",
            )
            self.coligadas_list.blockSignals(False)
            return

        conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={host};"
            f"DATABASE={db_name};"
            f"UID={username};"
            f"PWD={password};"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
        )

        t0 = time.monotonic()
        try:
            with pyodbc.connect(conn_str, timeout=10) as conn:
                cur = conn.cursor()
                cur.execute(sql)
                rows = cur.fetchall()
                columns = [desc[0].lower() for desc in cur.description] if cur.description else []
        except Exception as exc:
            dt = time.monotonic() - t0
            QMessageBox.warning(
                self,
                "Erro ao carregar coligadas",
                f"Falha ao executar a consulta de Coligadas ({dt:.3f}s):\n{exc}",
            )
            self.coligadas_list.blockSignals(False)
            return

        if not rows or not columns:
            self.coligadas_list.blockSignals(False)
            return

        def col_index(name: str) -> int | None:
            return columns.index(name) if name in columns else None

        idx_cod = col_index("codcoligada")
        idx_nome = col_index("nomefantasia") or col_index("coligada") or col_index("nome")
        if idx_cod is None or idx_nome is None:
            QMessageBox.warning(
                self,
                "Colunas não encontradas",
                "A consulta de Coligadas deve retornar CODCOLIGADA e NOMEFANTASIA (ou COLIGADA).",
            )
            self.coligadas_list.blockSignals(False)
            return

        seen: set = set()
        for row in rows:
            cod = row[idx_cod]
            nome = row[idx_nome]
            if cod in seen:
                continue
            seen.add(cod)
            label = "" if nome is None else str(nome)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cod)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.coligadas_list.addItem(item)

        self.coligadas_list.blockSignals(False)
        self.on_coligadas_changed()

    def on_coligadas_changed(self) -> None:
        item = self.coligadas_list.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole) == "__ALL__":
            state = item.checkState()
            self.coligadas_list.blockSignals(True)
            for i in range(1, self.coligadas_list.count()):
                self.coligadas_list.item(i).setCheckState(state)
            self.coligadas_list.blockSignals(False)
        self._sync_all_item()
        self.coligadas_summary.setText(self.get_coligadas_labels())

    def get_coligadas_csv(self) -> str:
        values: list[str] = []
        for i in range(1, self.coligadas_list.count()):
            item = self.coligadas_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                values.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return ",".join(values)

    def get_coligadas_labels(self) -> str:
        labels: list[str] = []
        for i in range(1, self.coligadas_list.count()):
            item = self.coligadas_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                labels.append(item.text())
        return ", ".join(labels)

    def set_coligadas_from_csv(self, csv_value: str) -> None:
        selected = {v.strip() for v in csv_value.split(",") if v.strip()}
        self.coligadas_list.blockSignals(True)
        for i in range(1, self.coligadas_list.count()):
            item = self.coligadas_list.item(i)
            code = str(item.data(Qt.ItemDataRole.UserRole))
            item.setCheckState(
                Qt.CheckState.Checked if code in selected else Qt.CheckState.Unchecked
            )
        self.coligadas_list.blockSignals(False)
        self.on_coligadas_changed()

    def get_coligadas_labels_from_csv(self, csv_value: str) -> str:
        selected = {v.strip() for v in csv_value.split(",") if v.strip()}
        labels: list[str] = []
        for i in range(1, self.coligadas_list.count()):
            item = self.coligadas_list.item(i)
            code = str(item.data(Qt.ItemDataRole.UserRole))
            if code in selected:
                labels.append(item.text())
        return ", ".join(labels)

    def _sync_all_item(self) -> None:
        if self.coligadas_list.count() == 0:
            return
        total = self.coligadas_list.count() - 1
        checked = 0
        for i in range(1, self.coligadas_list.count()):
            if self.coligadas_list.item(i).checkState() == Qt.CheckState.Checked:
                checked += 1
        all_item = self.coligadas_list.item(0)
        self.coligadas_list.blockSignals(True)
        if checked == 0:
            all_item.setCheckState(Qt.CheckState.Unchecked)
        elif checked == total:
            all_item.setCheckState(Qt.CheckState.Checked)
        else:
            all_item.setCheckState(Qt.CheckState.PartiallyChecked)
        self.coligadas_list.blockSignals(False)
