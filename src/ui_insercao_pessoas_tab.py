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


class InsercaoPessoasTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.proc: QProcess | None = None
        self.exec_timer = QElapsedTimer()
        self.exec_started = False

        self.last_summary_line: str = ""

        title = QLabel("Inserção de Pessoas")
        title.setObjectName("TabTitle")
        subtitle = QLabel("Crie e atualize usuários (alunos/professores) no Moodle, por USERNAME")
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

        self.chk_alunos = QCheckBox("Inserir/Atualizar Alunos")
        self.chk_professores = QCheckBox("Inserir/Atualizar Professores")
        self.chk_alunos.setChecked(True)
        self.chk_professores.setChecked(False)

        form_layout.addRow("Plataforma", self.platform_select)
        form_layout.addRow("Período", self.periodo_select)
        form_layout.addRow("", self.chk_alunos)
        form_layout.addRow("", self.chk_professores)

        self.execute_button = QPushButton("Executar")
        self.execute_button.setObjectName("ExecuteButton")
        self.execute_button.clicked.connect(self.on_execute)

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setObjectName("CancelButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.on_cancel)

        actions = QHBoxLayout()
        actions.addWidget(self.execute_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)

        self.log = QPlainTextEdit()
        self.log.setObjectName("Terminal")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Logs da inserção/atualização aparecerão aqui...")

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

    def _period_sort_key(self, catperiodo: str) -> tuple[int, int, str]:
        s = (catperiodo or "").strip()
        if len(s) >= 4 and s[:4].isdigit():
            year = int(s[:4])
            rest = s[4:].lstrip("-_/ ").strip()

            term = 0
            if rest:
                token = ""
                for ch in rest:
                    if ch.isdigit():
                        token += ch
                    else:
                        break
                if token:
                    try:
                        term = int(token)
                    except Exception:
                        term = 0

            return (year, term, s)

        return (0, 0, s)

    def load_platforms(self) -> None:
        self.platform_select.clear()
        for platform_id, name in list_platforms_for_select():
            self.platform_select.addItem(name, platform_id)

    def on_platform_changed(self) -> None:
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos", "Todos")
        self.periodo_select.reset_loaded()

    def populate_periodos(self) -> None:
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos", "Todos")

        platform_id = self.platform_select.currentData()
        if platform_id is None:
            self.append_log("Nenhuma plataforma selecionada; não carregando períodos.")
            return

        if not get_rm_config():
            self.append_log("Config do RM ausente; não carregando períodos.")
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

        sql = (
            "SELECT X.CODCOLIGADA, X.CATPERIODO "
            "FROM (" + base_no_order + ") X "
            f"WHERE X.CODCOLIGADA IN ({in_list}) "
        )

        host, db_name, username, password = config
        try:
            import pyodbc  # type: ignore
        except Exception as exc:
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

        self.append_log(f"Executando consulta RM: periodos (CODCOLIGADA IN ({in_list}))")
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
        self.append_log(f"Consulta RM periodos concluída em {dt:.3f}s ({len(rows)} linhas)")

        if not rows or not columns:
            return

        def idx(name: str):
            return columns.index(name) if name in columns else None

        idx_codcol = idx("codcoligada")
        idx_catperiodo = idx("catperiodo")

        if idx_codcol is None or idx_catperiodo is None:
            self.append_log("SQL de períodos deve retornar: CODCOLIGADA, CATPERIODO.")
            return

        seen_cat: set[str] = set()
        items: list[str] = []

        for row in rows:
            codcol = self._norm(row[idx_codcol])
            if not codcol or codcol not in allowed:
                continue

            catperiodo = "" if row[idx_catperiodo] is None else str(row[idx_catperiodo]).strip()
            if not catperiodo:
                continue

            if catperiodo in seen_cat:
                continue
            seen_cat.add(catperiodo)
            items.append(catperiodo)

        items.sort(key=self._period_sort_key, reverse=True)

        for catperiodo in items:
            self.periodo_select.addItem(catperiodo, catperiodo)

        self.append_log(f"Períodos adicionados (únicos): {len(items)}")

    def on_execute(self) -> None:
        if self.proc and self.proc.state() == QProcess.ProcessState.Running:
            QMessageBox.information(self, "Inserção de Pessoas", "Já existe uma execução em andamento.")
            return

        platform_id = self.platform_select.currentData()
        if platform_id is None:
            QMessageBox.warning(self, "Plataforma obrigatória", "Selecione uma plataforma.")
            return

        periodo_value = self.periodo_select.currentData()
        catperiodo = "" if periodo_value is None else str(periodo_value).strip()
        if catperiodo.lower() == "todos":
            catperiodo = ""

        do_alunos = self.chk_alunos.isChecked()
        do_prof = self.chk_professores.isChecked()
        if not do_alunos and not do_prof:
            QMessageBox.information(self, "Inserção de Pessoas", "Selecione ao menos um tipo (Alunos ou Professores).")
            return

        base_dir = Path(__file__).resolve().parent
        script = str(base_dir / "insercaopessoas.py")

        args = [
            "--platform-id",
            str(int(platform_id)),
            "--periodo",
            catperiodo,
            "--insert-alunos",
            "1" if do_alunos else "0",
            "--insert-professores",
            "1" if do_prof else "0",
        ]

        self.log.clear()
        self.last_summary_line = ""
        self.exec_timer.restart()
        self.exec_started = True

        self.execute_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self.append_log("Iniciando inserção/atualização...")
        self.append_log(f"Script: {Path(script).name}")

        self.proc = QProcess(self)
        self.proc.setProgram(sys.executable)

        env = self.proc.processEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        self.proc.setProcessEnvironment(env)

        self.proc.setArguments([script] + args)
        self.proc.readyReadStandardOutput.connect(self.on_proc_stdout)
        self.proc.readyReadStandardError.connect(self.on_proc_stderr)
        self.proc.finished.connect(self.on_proc_finished)
        self.proc.start()

    def on_cancel(self) -> None:
        if self.proc and self.proc.state() == QProcess.ProcessState.Running:
            self.append_log("Cancelando execução...")
            self.proc.terminate()
            if not self.proc.waitForFinished(1500):
                self.append_log("Processo não encerrou a tempo; forçando encerramento (kill).")
                self.proc.kill()
                self.proc.waitForFinished(1500)

        self.proc = None
        self.exec_started = False
        self.execute_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.append_log("Execução cancelada.")

    def on_proc_stdout(self) -> None:
        if not self.proc:
            return
        raw = bytes(self.proc.readAllStandardOutput())
        data = self._decode_output(raw)
        self._consume_output(data)

    def on_proc_stderr(self) -> None:
        if not self.proc:
            return
        raw = bytes(self.proc.readAllStandardError())
        data = self._decode_output(raw)
        self._consume_output(data)

    def _consume_output(self, text: str) -> None:
        if not text:
            return
        lines = text.splitlines() if "\n" in text else [text]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            self.append_log(line)
            if line.startswith("RESUMO_FINAL:"):
                self.last_summary_line = line

    def on_proc_finished(self) -> None:
        if not self.proc:
            return

        exit_code = self.proc.exitCode()
        self.proc = None

        self.execute_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.exec_started = False

        if exit_code != 0:
            self.append_log(f"Processo finalizou com erro (exit_code={exit_code}).")
            QMessageBox.critical(
                self,
                "Inserção de Pessoas",
                "A execução terminou com erro.\n\nVerifique o log para detalhes.",
            )
            return

        self.append_log("Execução finalizada com sucesso.")
        msg = "A execução terminou."
        if self.last_summary_line:
            msg = self.last_summary_line.replace("RESUMO_FINAL:", "Resumo:")

        QMessageBox.information(self, "Inserção de Pessoas", msg)

    def append_log(self, text: str) -> None:
        if not text:
            return

        prefix = ""
        if self.exec_started and self.exec_timer.isValid():
            prefix = f"[+{self.exec_timer.elapsed() / 1000:.3f}s] "

        self.log.appendPlainText(prefix + text)