from __future__ import annotations

import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QElapsedTimer, QProcess
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.db import get_platform_coligadas, get_rm_config, get_rm_queries, list_platforms_for_select
from ui_common import LazyComboBox


class ExecutionTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.proc: QProcess | None = None
        self.exec_timer = QElapsedTimer()
        self.exec_started = False

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

    def _decode_output(self, raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("latin-1", errors="replace")

    def _norm(self, v) -> str:
        if v is None:
            return ""
        s = str(v).strip()
        if not s:
            return ""
        try:
            f = float(s.replace(",", "."))
            i = int(f)
            if abs(f - i) < 1e-9:
                return str(i)
        except Exception:
            pass
        return s

    def _strip_sql(self, sql: str) -> str:
        sql = (sql or "").strip()
        if sql.endswith(";"):
            sql = sql[:-1].strip()
        return sql

    def _remove_last_order_by(self, sql: str) -> str:
        lower = sql.lower()
        pos = lower.rfind("order by")
        if pos == -1:
            return sql
        return sql[:pos].strip()

    def _sql_in_list(self, values: set[str]) -> str:
        cleaned: list[str] = []
        for v in sorted(values):
            v = self._norm(v)
            if not v:
                continue
            if v.isdigit():
                cleaned.append(v)
            else:
                cleaned.append("'" + v.replace("'", "''") + "'")
        return ", ".join(cleaned)

    def load_platforms(self) -> None:
        self.platform_select.clear()
        for platform_id, name in list_platforms_for_select():
            self.platform_select.addItem(name, platform_id)

    def on_platform_changed(self) -> None:
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos")
        self.periodo_select.reset_loaded()

    def populate_periodos(self) -> None:
        """
        Nova regra baseada na sua consulta:

        Consulta de períodos deve retornar:
        - IDPERLET (value do combo / filtro)
        - LABELPERIODO (label do combo)
        - CODCOLIGADA (para filtro por coligadas da plataforma)
        - CATPERIODO (auxiliar; pode existir duplicidade por modalidade, então deduplica)

        Regras do combo:
        - label = LABELPERIODO
        - value = IDPERLET
        """
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos")

        platform_id = self.platform_select.currentData()
        if platform_id is None:
            self.append_log("Nenhuma plataforma selecionada; não carregando períodos.")
            return

        col_csv = get_platform_coligadas(int(platform_id)) or ""
        allowed = {self._norm(c) for c in col_csv.split(",") if self._norm(c)}
        if not allowed:
            self.append_log("Plataforma não tem coligadas selecionadas; não carregando períodos.")
            return

        queries = get_rm_queries()
        config = get_rm_config()
        base_sql = queries.get("periodos", "").strip() if queries else ""
        if not base_sql or not config:
            self.append_log("Consulta/config do RM ausente; não carregando períodos.")
            return

        base_sql = self._strip_sql(base_sql)
        base_no_order = self._remove_last_order_by(base_sql)
        in_list = self._sql_in_list(allowed)
        if not in_list:
            self.append_log("Lista de coligadas inválida (IN vazio); não carregando períodos.")
            return

        # Filtra por CODCOLIGADA no SQL (subquery), não depende de alias do SQL original
        sql = (
            "SELECT X.CODCOLIGADA, X.IDPERLET, X.LABELPERIODO, X.CATPERIODO "
            "FROM ("
            + base_no_order
            + ") X "
            f"WHERE X.CODCOLIGADA IN ({in_list}) "
            "ORDER BY X.CATPERIODO DESC, X.IDPERLET DESC"
        )

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

        self.append_log(f"Executando consulta RM: periodos (filtrado por CODCOLIGADA IN ({in_list}))")
        t0 = time.monotonic()

        try:
            with pyodbc.connect(conn_str, timeout=10) as conn:
                cur = conn.cursor()
                cur.execute(sql)
                rows = cur.fetchall()
                columns = [desc[0].lower() for desc in cur.description] if cur.description else []
        except Exception as exc:
            dt = time.monotonic() - t0
            self.append_log(f"Consulta RM periodos falhou em {dt:.3f}s: {exc}")
            return

        dt = time.monotonic() - t0
        self.append_log(f"Consulta RM periodos concluída em {dt:.3f}s ({len(rows)} linhas filtradas)")

        if not rows or not columns:
            return

        def idx(name: str):
            return columns.index(name) if name in columns else None

        idx_codcol = idx("codcoligada")
        idx_idperlet = idx("idperlet")
        idx_label = idx("labelperiodo")
        idx_catperiodo = idx("catperiodo")

        if idx_codcol is None or idx_idperlet is None or idx_label is None:
            self.append_log("SQL de períodos deve retornar: CODCOLIGADA, IDPERLET, LABELPERIODO (e opcional CATPERIODO).")
            return

        # Deduplica (robusto) e ordena por IDPERLET desc
        seen: set[tuple[str, str, str]] = set()
        items: list[tuple[int, str, str]] = []  # (idperlet_int, label, idperlet_str)

        for row in rows:
            codcol = self._norm(row[idx_codcol])
            if not codcol or codcol not in allowed:
                continue

            idperlet_str = self._norm(row[idx_idperlet])
            label = "" if row[idx_label] is None else str(row[idx_label]).strip()
            catperiodo = ""
            if idx_catperiodo is not None:
                catperiodo = "" if row[idx_catperiodo] is None else str(row[idx_catperiodo]).strip()

            if not idperlet_str or not label:
                continue

            key = (idperlet_str, label, catperiodo)
            if key in seen:
                continue
            seen.add(key)

            try:
                idperlet_int = int(float(idperlet_str))
            except Exception:
                idperlet_int = 0

            items.append((idperlet_int, label, idperlet_str))

        items.sort(key=lambda x: x[0], reverse=True)

        added = 0
        for _id_int, label, idperlet_str in items:
            self.periodo_select.addItem(label, idperlet_str)
            added += 1

        self.append_log(f"Períodos adicionados: {added}")

    def on_execute(self) -> None:
        if self.platform_select.currentIndex() < 0:
            QMessageBox.warning(self, "Plataforma obrigatória", "Selecione uma plataforma.")
            return

        if self.proc and self.proc.state() == QProcess.ProcessState.Running:
            QMessageBox.information(self, "Execução", "Já existe uma execução em andamento.")
            return

        platform_id = str(self.platform_select.currentData())
        periodo_value = self.periodo_select.currentData()  # IDPERLET
        idperlet = "" if periodo_value is None else str(periodo_value).strip()
        create_cats = "1" if self.create_categories.isChecked() else "0"

        self.log.clear()
        self.exec_timer.restart()
        self.exec_started = True

        self.append_log("Iniciando execução...")
        self.execute_button.setEnabled(False)

        self.proc = QProcess(self)
        self.proc.setProgram(sys.executable)

        env = self.proc.processEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        self.proc.setProcessEnvironment(env)

        script_path = str(Path(__file__).resolve().parent / "categorias.py")

        self.proc.setArguments(
            [
                script_path,
                "--platform-id",
                platform_id,
                "--periodo",
                idperlet,  # IDPERLET vai para o filtro
                "--create-categories",
                create_cats,
            ]
        )
        self.proc.readyReadStandardOutput.connect(self.on_proc_stdout)
        self.proc.readyReadStandardError.connect(self.on_proc_stderr)
        self.proc.finished.connect(self.on_proc_finished)
        self.proc.start()

    def on_proc_stdout(self) -> None:
        if not self.proc:
            return
        raw = bytes(self.proc.readAllStandardOutput())
        data = self._decode_output(raw)
        self.append_log(data.strip())

    def on_proc_stderr(self) -> None:
        if not self.proc:
            return
        raw = bytes(self.proc.readAllStandardError())
        data = self._decode_output(raw)
        self.append_log(data.strip())

    def on_proc_finished(self) -> None:
        self.append_log("Execução finalizada.")
        self.execute_button.setEnabled(True)
        self.exec_started = False

    def append_log(self, text: str) -> None:
        if not text:
            return

        lines = text.splitlines() if "\n" in text else [text]

        prefix = ""
        if self.exec_started and self.exec_timer.isValid():
            prefix = f"[+{self.exec_timer.elapsed() / 1000:.3f}s] "

        for line in lines:
            line = line.strip()
            if not line:
                continue
            self.log.appendPlainText(prefix + line)
