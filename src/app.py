from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
            QMessageBox.warning(
                self,
                "Campos obrigatórios",
                "Preencha Plataforma, URL e Token para salvar.",
            )
            return
        if self.selected_id is None:
            create_platform(name, url, token)
        else:
            update_platform(self.selected_id, name, url, token)
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

        self.filiais_input = QPlainTextEdit()
        self.filiais_input.setPlaceholderText("SQL para Filiais")
        self.filiais_input.setObjectName("SqlField")

        self.niveis_input = QPlainTextEdit()
        self.niveis_input.setPlaceholderText("SQL para Níveis de ensino")
        self.niveis_input.setObjectName("SqlField")

        self.periodos_input = QPlainTextEdit()
        self.periodos_input.setPlaceholderText("SQL para Períodos")
        self.periodos_input.setObjectName("SqlField")

        self.cursos_input = QPlainTextEdit()
        self.cursos_input.setPlaceholderText("SQL para Cursos")
        self.cursos_input.setObjectName("SqlField")

        self.turmas_input = QPlainTextEdit()
        self.turmas_input.setPlaceholderText("SQL para Turmas")
        self.turmas_input.setObjectName("SqlField")

        self.disciplinas_input = QPlainTextEdit()
        self.disciplinas_input.setPlaceholderText("SQL para Disciplinas")
        self.disciplinas_input.setObjectName("SqlField")

        self.professores_input = QPlainTextEdit()
        self.professores_input.setPlaceholderText("SQL para Professores")
        self.professores_input.setObjectName("SqlField")

        self.alunos_input = QPlainTextEdit()
        self.alunos_input.setPlaceholderText("SQL para Alunos")
        self.alunos_input.setObjectName("SqlField")

        inner_tabs = QTabWidget()
        inner_tabs.setObjectName("InnerTabs")
        inner_tabs.addTab(
            self._wrap_sql("Coligadas", "coligadas", self.coligadas_input),
            "Coligadas",
        )
        inner_tabs.addTab(
            self._wrap_sql("Filiais", "filiais", self.filiais_input),
            "Filiais",
        )
        inner_tabs.addTab(
            self._wrap_sql("Níveis de ensino", "niveis_ensino", self.niveis_input),
            "Níveis de ensino",
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
            self._wrap_sql("Disciplinas", "disciplinas", self.disciplinas_input),
            "Disciplinas",
        )
        inner_tabs.addTab(
            self._wrap_sql("Professores", "professores", self.professores_input),
            "Professores",
        )
        inner_tabs.addTab(
            self._wrap_sql("Alunos", "alunos", self.alunos_input),
            "Alunos",
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
            self.filiais_input.setPlainText(current.get("filiais", ""))
            self.niveis_input.setPlainText(current.get("niveis_ensino", ""))
            self.periodos_input.setPlainText(current.get("periodos", ""))
            self.cursos_input.setPlainText(current.get("cursos", ""))
            self.turmas_input.setPlainText(current.get("turmas", ""))
            self.disciplinas_input.setPlainText(current.get("disciplinas", ""))
            self.professores_input.setPlainText(current.get("professores", ""))
            self.alunos_input.setPlainText(current.get("alunos", ""))

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
            "filiais": self.filiais_input.toPlainText().strip(),
            "niveis_ensino": self.niveis_input.toPlainText().strip(),
            "periodos": self.periodos_input.toPlainText().strip(),
            "cursos": self.cursos_input.toPlainText().strip(),
            "turmas": self.turmas_input.toPlainText().strip(),
            "disciplinas": self.disciplinas_input.toPlainText().strip(),
            "professores": self.professores_input.toPlainText().strip(),
            "alunos": self.alunos_input.toPlainText().strip(),
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
            "filiais": self.filiais_input.toPlainText().strip(),
            "niveis_ensino": self.niveis_input.toPlainText().strip(),
            "periodos": self.periodos_input.toPlainText().strip(),
            "cursos": self.cursos_input.toPlainText().strip(),
            "turmas": self.turmas_input.toPlainText().strip(),
            "disciplinas": self.disciplinas_input.toPlainText().strip(),
            "professores": self.professores_input.toPlainText().strip(),
            "alunos": self.alunos_input.toPlainText().strip(),
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
