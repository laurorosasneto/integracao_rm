from __future__ import annotations

import sys

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QProcess, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.db import (
    create_platform,
    delete_platform,
    get_config,
    get_rm_config,
    get_rm_queries,
    get_platform_coligadas,
    list_platforms_for_select,
    list_platforms,
    set_config,
    set_rm_config,
    set_rm_queries,
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
        try:
            with pyodbc.connect(conn_str, timeout=10) as conn:
                cur = conn.cursor()
                cur.execute(sql)
                rows = cur.fetchall()
                columns = [desc[0].lower() for desc in cur.description] if cur.description else []
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Erro ao carregar coligadas",
                f"Falha ao executar a consulta de Coligadas:\n{exc}",
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
                "A consulta de Coligadas deve retornar CODCOLIGADA e NOMEFANTASIA.",
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


class RMQueriesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        title = QLabel("Consultas RM")
        title.setObjectName("TabTitle")
        subtitle = QLabel("Cole as consultas SQL utilizadas para cada entidade")
        subtitle.setObjectName("TabSubtitle")

        self.coligadas_input = QPlainTextEdit()
        self.coligadas_input.setPlaceholderText("SQL para Coligadas")
        self.coligadas_input.setObjectName("SqlField")

        self.periodos_input = QPlainTextEdit()
        self.periodos_input.setPlaceholderText("SQL para Períodos")
        self.periodos_input.setObjectName("SqlField")

        self.cursos_input = QPlainTextEdit()
        self.cursos_input.setPlaceholderText("SQL para Cursos")
        self.cursos_input.setObjectName("SqlField")

        self.turmas_input = QPlainTextEdit()
        self.turmas_input.setPlaceholderText("SQL para Turmas")
        self.turmas_input.setObjectName("SqlField")

        self.salas_input = QPlainTextEdit()
        self.salas_input.setPlaceholderText("SQL para Salas")
        self.salas_input.setObjectName("SqlField")

        inner_tabs = QTabWidget()
        inner_tabs.setObjectName("InnerTabs")
        inner_tabs.addTab(
            self._wrap_sql("Coligadas", "coligadas", self.coligadas_input),
            "Coligadas",
        )
        inner_tabs.addTab(
            self._wrap_sql("Períodos", "periodos", self.periodos_input),
            "Períodos",
        )
        inner_tabs.addTab(
            self._wrap_sql("Cursos", "cursos", self.cursos_input),
            "Cursos",
        )
        inner_tabs.addTab(
            self._wrap_sql("Turmas", "turmas", self.turmas_input),
            "Turmas",
        )
        inner_tabs.addTab(
            self._wrap_sql("Salas", "salas", self.salas_input),
            "Salas",
        )

        self.save_button = QPushButton("Salvar consultas")
        self.save_button.clicked.connect(self.on_save)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addWidget(inner_tabs)
        content_layout.addWidget(self.save_button)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("TabScroll")
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

        current = get_rm_queries()
        if current:
            self.coligadas_input.setPlainText(current.get("coligadas", ""))
            self.periodos_input.setPlainText(current.get("periodos", ""))
            self.cursos_input.setPlainText(current.get("cursos", ""))
            self.turmas_input.setPlainText(current.get("turmas", ""))
            self.salas_input.setPlainText(current.get("salas", ""))

    def _wrap_sql(self, label: str, key: str, field: QPlainTextEdit) -> QWidget:
        container = QFrame()
        container.setObjectName("FormCard")
        layout = QVBoxLayout(container)
        title = QLabel(label)
        title.setObjectName("CardTitle")
        test_button = QPushButton("Testar consulta")
        test_button.clicked.connect(lambda: self.on_test(key))
        actions = QHBoxLayout()
        actions.addWidget(test_button)
        actions.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(field)
        layout.addLayout(actions)
        return container

    def on_save(self) -> None:
        values = {
            "coligadas": self.coligadas_input.toPlainText().strip(),
            "periodos": self.periodos_input.toPlainText().strip(),
            "cursos": self.cursos_input.toPlainText().strip(),
            "turmas": self.turmas_input.toPlainText().strip(),
            "salas": self.salas_input.toPlainText().strip(),
        }
        set_rm_queries(values)
        QMessageBox.information(
            self,
            "Salvo",
            "Consultas RM salvas com sucesso.",
        )

    def on_test(self, key: str) -> None:
        query_map = {
            "coligadas": self.coligadas_input.toPlainText().strip(),
            "periodos": self.periodos_input.toPlainText().strip(),
            "cursos": self.cursos_input.toPlainText().strip(),
            "turmas": self.turmas_input.toPlainText().strip(),
            "salas": self.salas_input.toPlainText().strip(),
        }
        sql = query_map.get(key, "")
        if not sql:
            QMessageBox.warning(
                self,
                "Consulta vazia",
                "Cole uma consulta SQL antes de testar.",
            )
            return

        config = get_rm_config()
        if not config:
            QMessageBox.warning(
                self,
                "Configuração ausente",
                "Configure o acesso ao RM na aba TOTVS RM antes de testar.",
            )
            return

        host, db_name, username, password = config
        try:
            import pyodbc  # type: ignore
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(
                self,
                "Driver não disponível",
                f"Erro ao carregar pyodbc: {exc}",
            )
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
        try:
            with pyodbc.connect(conn_str, timeout=10) as conn:
                cur = conn.cursor()
                cur.execute(sql)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchall()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Erro ao executar",
                f"Falha ao executar a consulta:\n{exc}",
            )
            return

        dialog = QueryResultDialog(self, columns, rows)
        dialog.exec()


class QueryResultDialog(QDialog):
    def __init__(self, parent: QWidget | None, columns: list[str], rows: list[tuple]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resultado da consulta")
        self.resize(900, 600)

        self.all_rows = rows
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filtrar resultados...")

        self.table = QTableView()
        self.table.setObjectName("DataTable")
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        string_rows = [[("" if v is None else str(v)) for v in row] for row in rows]
        self.model = PaginatedTableModel(columns, string_rows)
        self.table.setModel(self.model)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

        self.filter_input.textChanged.connect(self.model.set_filter)
        self.table.horizontalHeader().sortIndicatorChanged.connect(self.model.sort)

        self.prev_button = QPushButton("Anterior")
        self.next_button = QPushButton("Próxima")
        self.goto_input = QLineEdit()
        self.goto_input.setPlaceholderText("Ir para")
        self.goto_input.setMaximumWidth(80)
        self.goto_button = QPushButton("Ir")
        self.export_button = QPushButton("Exportar CSV")
        self.page_size = QComboBox()
        self.page_size.addItems(["25", "50", "100"])
        self.page_size.setCurrentText("50")

        self.prev_button.clicked.connect(self.on_prev)
        self.next_button.clicked.connect(self.on_next)
        self.page_size.currentTextChanged.connect(self.on_page_size)
        self.goto_button.clicked.connect(self.on_goto)
        self.export_button.clicked.connect(self.on_export)

        self.page_info = QLabel("")
        info = QLabel(f"{len(rows)} linhas carregadas.")
        info.setObjectName("TabSubtitle")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Por página:"))
        controls.addWidget(self.page_size)
        controls.addStretch(1)
        controls.addWidget(self.prev_button)
        controls.addWidget(self.next_button)
        controls.addWidget(self.goto_input)
        controls.addWidget(self.goto_button)
        controls.addWidget(self.page_info)
        controls.addStretch(1)
        controls.addWidget(self.export_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.filter_input)
        layout.addWidget(self.table)
        layout.addLayout(controls)
        layout.addWidget(info)

        self.model.set_page_size(int(self.page_size.currentText()))
        self.update_page_info()

    def update_page_info(self) -> None:
        total_pages = self.model.total_pages
        current_page = self.model.page_index + 1
        total_rows = self.model.total_rows
        self.page_info.setText(f"Página {current_page} de {total_pages} | {total_rows} linhas")
        self.prev_button.setEnabled(self.model.page_index > 0)
        self.next_button.setEnabled(self.model.page_index < total_pages - 1)

    def on_prev(self) -> None:
        self.model.set_page(self.model.page_index - 1)
        self.update_page_info()

    def on_next(self) -> None:
        self.model.set_page(self.model.page_index + 1)
        self.update_page_info()

    def on_page_size(self, value: str) -> None:
        self.model.set_page_size(int(value))
        self.update_page_info()

    def on_goto(self) -> None:
        text = self.goto_input.text().strip()
        if not text.isdigit():
            return
        page = int(text)
        if page < 1:
            page = 1
        if page > self.model.total_pages:
            page = self.model.total_pages
        self.model.set_page(page - 1)
        self.update_page_info()

    def on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar CSV",
            "resultado.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            import csv

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(self.model.columns)
                for row in self.model.filtered_rows:
                    writer.writerow(row)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Erro ao exportar",
                f"Falha ao exportar CSV:\n{exc}",
            )
            return
        QMessageBox.information(
            self,
            "Exportado",
            "CSV exportado com sucesso.",
        )


class PaginatedTableModel(QAbstractTableModel):
    def __init__(self, columns: list[str], rows: list[list[str]]) -> None:
        super().__init__()
        self.columns = columns
        self.all_rows = rows
        self.filter_text = ""
        self.page_size = 50
        self.page_index = 0
        self.sort_column = -1
        self.sort_order = Qt.SortOrder.AscendingOrder
        self.filtered_rows: list[list[str]] = []
        self.page_rows: list[list[str]] = []
        self.total_rows = 0
        self.total_pages = 1
        self._recompute()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return len(self.page_rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return len(self.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.page_rows[index.row()][index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.columns[section]
        return str(section + 1)

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self.sort_column = column
        self.sort_order = order
        self._recompute()

    def set_filter(self, text: str) -> None:
        self.filter_text = text.strip().lower()
        self.page_index = 0
        self._recompute()

    def set_page_size(self, size: int) -> None:
        self.page_size = max(1, size)
        self.page_index = 0
        self._recompute()

    def set_page(self, index: int) -> None:
        self.page_index = max(0, min(index, self.total_pages - 1))
        self._recompute()

    def _recompute(self) -> None:
        def match(row: list[str]) -> bool:
            if not self.filter_text:
                return True
            return any(self.filter_text in (cell or "").lower() for cell in row)

        self.filtered_rows = [row for row in self.all_rows if match(row)]

        if 0 <= self.sort_column < len(self.columns):
            self.filtered_rows.sort(
                key=lambda r: (r[self.sort_column] or "").lower(),
                reverse=self.sort_order == Qt.SortOrder.DescendingOrder,
            )

        self.total_rows = len(self.filtered_rows)
        self.total_pages = max(1, (self.total_rows + self.page_size - 1) // self.page_size)
        self.page_index = max(0, min(self.page_index, self.total_pages - 1))

        start = self.page_index * self.page_size
        end = start + self.page_size
        self.page_rows = self.filtered_rows[start:end]

        self.layoutChanged.emit()


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


class ExecutionTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.proc: QProcess | None = None

        title = QLabel("Execução")
        title.setObjectName("TabTitle")
        subtitle = QLabel("Execute a criação de categorias no Moodle")
        subtitle.setObjectName("TabSubtitle")

        form = QFrame()
        form.setObjectName("FormCard")
        form_layout = QFormLayout(form)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.platform_select = QComboBox()
        self.platform_select.setObjectName("Select")
        self.platform_select.currentIndexChanged.connect(self.on_platform_changed)

        self.periodo_select = LazyComboBox()
        self.periodo_select.setObjectName("Select")
        self.periodo_select.set_loader(self.populate_periodos)

        self.create_categories = QCheckBox("Criar Categorias")
        self.create_categories.setChecked(True)

        form_layout.addRow("Plataforma", self.platform_select)
        form_layout.addRow("Período", self.periodo_select)
        form_layout.addRow("", self.create_categories)

        self.execute_button = QPushButton("Executar")
        self.execute_button.setObjectName("ExecuteButton")
        self.execute_button.clicked.connect(self.on_execute)

        actions = QHBoxLayout()
        actions.addWidget(self.execute_button)
        actions.addStretch(1)

        self.log = QPlainTextEdit()
        self.log.setObjectName("Terminal")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Logs da execução aparecerão aqui...")

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(form)
        layout.addLayout(actions)
        layout.addWidget(self.log)

        self.load_platforms()

    def load_platforms(self) -> None:
        self.platform_select.clear()
        for platform_id, name in list_platforms_for_select():
            self.platform_select.addItem(name, platform_id)

    def on_platform_changed(self) -> None:
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos")
        self.periodo_select.reset_loaded()

    def populate_periodos(self) -> None:
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos")

        queries = get_rm_queries()
        config = get_rm_config()
        sql = queries.get("periodos", "").strip() if queries else ""
        if not sql or not config:
            return

        host, db_name, username, password = config
        try:
            import pyodbc  # type: ignore
        except Exception as exc:  # pragma: no cover
            self.append_log(f"Erro ao carregar pyodbc: {exc}")
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
        try:
            with pyodbc.connect(conn_str, timeout=10) as conn:
                cur = conn.cursor()
                cur.execute(sql)
                rows = cur.fetchall()
                columns = [desc[0].lower() for desc in cur.description] if cur.description else []
        except Exception as exc:
            self.append_log(f"Erro ao carregar períodos: {exc}")
            return

        if not rows:
            return

        def pick_index(candidates: list[str]) -> int | None:
            for name in candidates:
                if name in columns:
                    return columns.index(name)
            return None

        idx_periodo = pick_index(["periodo", "codperiodo", "codper", "codperlet"])
        idx_coligada = pick_index(["codcoligada"])
        if idx_periodo is None and len(columns) == 1:
            idx_periodo = 0

        allowed = set()
        platform_id = self.platform_select.currentData()
        if platform_id is not None:
            col_csv = get_platform_coligadas(int(platform_id)) or ""
            allowed = {c.strip() for c in col_csv.split(",") if c.strip()}

        seen: set = set()
        for row in rows:
            if idx_periodo is None:
                continue
            if idx_coligada is not None and allowed:
                if str(row[idx_coligada]) not in allowed:
                    continue
            value = row[idx_periodo]
            if value in seen:
                continue
            seen.add(value)
            label = "" if value is None else str(value)
            self.periodo_select.addItem(label, value)

    def on_execute(self) -> None:
        if self.platform_select.currentIndex() < 0:
            QMessageBox.warning(self, "Plataforma obrigatória", "Selecione uma plataforma.")
            return

        if self.proc and self.proc.state() == QProcess.ProcessState.Running:
            QMessageBox.information(self, "Execução", "Já existe uma execução em andamento.")
            return

        platform_id = str(self.platform_select.currentData())
        periodo = self.periodo_select.currentText()
        create_cats = "1" if self.create_categories.isChecked() else "0"

        self.append_log("Iniciando execução...")
        self.execute_button.setEnabled(False)

        self.proc = QProcess(self)
        self.proc.setProgram(sys.executable)
        self.proc.setArguments(
            ["categorias.py", "--platform-id", platform_id, "--periodo", periodo, "--create-categories", create_cats]
        )
        self.proc.readyReadStandardOutput.connect(self.on_proc_stdout)
        self.proc.readyReadStandardError.connect(self.on_proc_stderr)
        self.proc.finished.connect(self.on_proc_finished)
        self.proc.start()

    def on_proc_stdout(self) -> None:
        if not self.proc:
            return
        data = self.proc.readAllStandardOutput().data().decode("utf-8", errors="ignore")
        self.append_log(data.strip())

    def on_proc_stderr(self) -> None:
        if not self.proc:
            return
        data = self.proc.readAllStandardError().data().decode("utf-8", errors="ignore")
        self.append_log(data.strip())

    def on_proc_finished(self) -> None:
        self.append_log("Execução finalizada.")
        self.execute_button.setEnabled(True)

    def append_log(self, text: str) -> None:
        if not text:
            return
        self.log.appendPlainText(text)


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
        tabs.addTab(RMTab(), "TOTVS RM")
        tabs.addTab(RMQueriesTab(), "Consultas RM")
        tabs.addTab(ExecutionTab(), "Execução")

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
        #InnerTabs::pane {
            border: none;
            margin: 0 8px 8px 8px;
        }
        #InnerTabs QTabBar::tab {
            background: #f3f4f6;
            color: #374151;
            border: none;
            padding: 8px 12px;
            margin-right: 6px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
        }
        #InnerTabs QTabBar::tab:selected {
            background: #1f2937;
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
        QPlainTextEdit#SqlField {
            border: 1px solid #d1d5db;
            border-radius: 8px;
            padding: 8px 10px;
            background: #f9fafb;
            min-height: 200px;
        }
        QPlainTextEdit#SqlField:focus {
            border: 1px solid #3b82f6;
            background: #ffffff;
        }
        QPlainTextEdit#Terminal {
            background: #0b1220;
            color: #e5e7eb;
            border-radius: 10px;
            padding: 10px;
            font-family: Consolas, "Courier New", monospace;
            min-height: 220px;
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
        #ExecuteButton {
            background: #16a34a;
        }
        #ExecuteButton:hover {
            background: #15803d;
        }
        #ExecuteButton:pressed {
            background: #166534;
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
