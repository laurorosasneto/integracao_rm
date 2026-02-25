from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from core.db import get_rm_config, get_rm_queries, set_rm_queries
from ui_query_result_dialog import QueryResultDialog


class RMQueriesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        title = QLabel("Consultas RM")
        title.setObjectName("TabTitle")
        subtitle = QLabel("Cole as consultas SQL utilizadas para cada entidade")
        subtitle.setObjectName("TabSubtitle")

        # Consultas principais
        self.coligadas_input = QPlainTextEdit()
        self.coligadas_input.setPlaceholderText("SQL para Coligadas")
        self.coligadas_input.setObjectName("SqlField")

        self.periodos_input = QPlainTextEdit()
        self.periodos_input.setPlaceholderText("SQL para Períodos")
        self.periodos_input.setObjectName("SqlField")

        # Importante: persistimos no campo `cursos`
        self.categorias_input = QPlainTextEdit()
        self.categorias_input.setPlaceholderText("SQL base para Categorias/Turmas/Salas")
        self.categorias_input.setObjectName("SqlField")

        # NOVO: Pessoas
        self.alunos_input = QPlainTextEdit()
        self.alunos_input.setPlaceholderText("SQL para Alunos (formato será definido na próxima etapa)")
        self.alunos_input.setObjectName("SqlField")

        self.professores_input = QPlainTextEdit()
        self.professores_input.setPlaceholderText("SQL para Professores (formato será definido na próxima etapa)")
        self.professores_input.setObjectName("SqlField")

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
            self._wrap_sql("Categorias/Turmas/Salas", "cursos", self.categorias_input),
            "Categorias/Turmas/Salas",
        )
        inner_tabs.addTab(
            self._wrap_sql("Alunos", "alunos", self.alunos_input),
            "Alunos",
        )
        inner_tabs.addTab(
            self._wrap_sql("Professores", "professores", self.professores_input),
            "Professores",
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

        # Carrega valores atuais
        current = get_rm_queries()
        if current:
            self.coligadas_input.setPlainText(current.get("coligadas", "") or "")
            self.periodos_input.setPlainText(current.get("periodos", "") or "")
            # Atenção: "cursos" é a query base Categorias/Turmas/Salas
            self.categorias_input.setPlainText(current.get("cursos", "") or "")
            self.alunos_input.setPlainText(current.get("alunos", "") or "")
            self.professores_input.setPlainText(current.get("professores", "") or "")

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
        # Mantemos no banco (retrocompatibilidade):
        # - `cursos` = base Categorias/Turmas/Salas
        # - `turmas` e `salas` ficam vazios (não usados mais)
        values = {
            "coligadas": self.coligadas_input.toPlainText().strip(),
            "periodos": self.periodos_input.toPlainText().strip(),
            "cursos": self.categorias_input.toPlainText().strip(),
            "turmas": "",
            "salas": "",
            "alunos": self.alunos_input.toPlainText().strip(),
            "professores": self.professores_input.toPlainText().strip(),
        }

        # Regras atuais: obrigatórias apenas as 3 consultas estruturais.
        if not values["coligadas"] or not values["periodos"] or not values["cursos"]:
            QMessageBox.warning(
                self,
                "Campos obrigatórios",
                "Preencha as três consultas: Coligadas, Períodos e Categorias/Turmas/Salas.",
            )
            return

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
            "cursos": self.categorias_input.toPlainText().strip(),
            "alunos": self.alunos_input.toPlainText().strip(),
            "professores": self.professores_input.toPlainText().strip(),
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