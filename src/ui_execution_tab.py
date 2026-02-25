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

from core.db import (
    get_platform_coligadas,
    get_rm_config,
    get_rm_queries,
    list_platforms_for_select,
    list_salas_modelo,
)
from ui_common import LazyComboBox


class ExecutionTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.proc: QProcess | None = None
        self.exec_timer = QElapsedTimer()
        self.exec_started = False

        # fila de scripts a executar
        self.queue: list[dict] = []
        self.current_step: str = ""

        title = QLabel("Execução")
        title.setObjectName("TabTitle")
        subtitle = QLabel("Execute a criação de categorias e cursos (disciplinas) no Moodle")
        subtitle.setObjectName("TabSubtitle")

        form = QFrame()
        form.setObjectName("FormCard")
        form_layout = QFormLayout(form)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.platform_select = QComboBox()
        self.platform_select.setObjectName("Select")
        self.platform_select.currentIndexChanged.connect(self.on_platform_changed)

        self.sala_modelo_select = QComboBox()
        self.sala_modelo_select.setObjectName("Select")

        self.periodo_select = LazyComboBox()
        self.periodo_select.setObjectName("Select")
        self.periodo_select.set_loader(self.populate_periodos)

        self.create_categories = QCheckBox("Criar Categorias")
        self.create_categories.setChecked(True)

        self.create_courses = QCheckBox("Criar Salas (Cursos/Disciplinas)")
        self.create_courses.setChecked(True)

        form_layout.addRow("Plataforma", self.platform_select)
        form_layout.addRow("Sala Modelo", self.sala_modelo_select)
        form_layout.addRow("Período", self.periodo_select)
        form_layout.addRow("", self.create_categories)
        form_layout.addRow("", self.create_courses)

        self.execute_button = QPushButton("Executar")
        self.execute_button.setObjectName("ExecuteButton")
        self.execute_button.clicked.connect(self.on_execute)

        # NOVO: Botão Cancelar
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
        self.log.setPlaceholderText("Logs da execução aparecerão aqui...")

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(form)
        layout.addLayout(actions)
        layout.addWidget(self.log)

        self.load_platforms()
        self.load_salas_modelo()

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

    def load_salas_modelo(self) -> None:
        self.sala_modelo_select.blockSignals(True)
        self.sala_modelo_select.clear()
        self.sala_modelo_select.addItem("Padrão (SALAS)", None)

        platform_id = self.platform_select.currentData()
        if platform_id is None:
            self.sala_modelo_select.blockSignals(False)
            return

        try:
            pid = int(platform_id)
        except Exception:
            self.sala_modelo_select.blockSignals(False)
            return

        # (id, created_at, platform_id, platform_name, name, moodle_id, extra_filter, updated_at)
        for row in list_salas_modelo():
            sala_id = int(row[0])
            row_platform_id = int(row[2])
            nome = str(row[4] or "").strip()
            if row_platform_id != pid:
                continue
            if not nome:
                continue
            self.sala_modelo_select.addItem(nome, sala_id)

        self.sala_modelo_select.blockSignals(False)

    def on_platform_changed(self) -> None:
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos", "Todos")
        self.periodo_select.reset_loaded()
        self.load_salas_modelo()

    def populate_periodos(self) -> None:
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos", "Todos")

        platform_id = self.platform_select.currentData()
        if platform_id is None:
            self.append_log("Nenhuma plataforma selecionada; não carregando períodos.")
            return

        col_csv = get_rm_config()  # apenas para checagem rápida de config
        if not col_csv:
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
        if self.platform_select.currentIndex() < 0:
            QMessageBox.warning(self, "Plataforma obrigatória", "Selecione uma plataforma.")
            return

        if self.proc and self.proc.state() == QProcess.ProcessState.Running:
            QMessageBox.information(self, "Execução", "Já existe uma execução em andamento.")
            return

        platform_id = str(self.platform_select.currentData())

        sala_modelo_id = self.sala_modelo_select.currentData()
        sala_modelo_arg = "" if sala_modelo_id is None else str(int(sala_modelo_id))

        periodo_value = self.periodo_select.currentData()
        catperiodo = "" if periodo_value is None else str(periodo_value).strip()
        if catperiodo.lower() == "todos":
            catperiodo = ""

        do_categorias = self.create_categories.isChecked()
        do_salas = self.create_courses.isChecked()

        if not do_categorias and not do_salas:
            QMessageBox.information(self, "Execução", "Selecione ao menos uma opção (Categorias ou Salas).")
            return

        if do_salas and not sala_modelo_arg:
            QMessageBox.warning(
                self,
                "Sala Modelo obrigatória",
                "Para criar Salas (Cursos/Disciplinas) é obrigatório selecionar uma Sala Modelo.",
            )
            return

        self.log.clear()
        self.exec_timer.restart()
        self.exec_started = True
        self.execute_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self.append_log("Iniciando execução...")

        if sala_modelo_arg:
            self.append_log(f"Sala Modelo: {self.sala_modelo_select.currentText()} (id={sala_modelo_arg})")
        else:
            self.append_log("Sala Modelo: Padrão (SALAS)")

        self.queue = []

        base_dir = Path(__file__).resolve().parent

        # NOVO FLUXO:
        # - Se o usuário marcar Categorias + Salas, executa somente categorias.py, que cria as salas turma-a-turma
        #   no momento em que cria/encontra cada turma.
        # - Se o usuário marcar APENAS Salas (Categorias desmarcado), executa salas.py (backfill).
        if do_categorias:
            cat_args = [
                "--platform-id",
                platform_id,
                "--periodo",
                catperiodo,
                "--create-categories",
                "1",
                "--create-courses",
                "1" if do_salas else "0",
            ]
            if do_salas:
                cat_args += ["--sala-modelo-id", sala_modelo_arg]
            elif sala_modelo_arg:
                # compatibilidade: manter o arg sem efeito quando salas não estiverem marcadas
                cat_args += ["--sala-modelo-id", sala_modelo_arg]

            self.queue.append(
                {
                    "name": "Categorias" + (" + Salas" if do_salas else ""),
                    "script": str(base_dir / "categorias.py"),
                    "args": cat_args,
                }
            )

        if do_salas and not do_categorias:
            self.queue.append(
                {
                    "name": "Salas (Cursos/Disciplinas)",
                    "script": str(base_dir / "salas.py"),
                    "args": [
                        "--platform-id",
                        platform_id,
                        "--periodo",
                        catperiodo,
                        "--create-courses",
                        "1",
                        "--sala-modelo-id",
                        sala_modelo_arg,
                    ],
                }
            )

        self._start_next_step()

    def on_cancel(self) -> None:
        # Cancelamento global do pipeline (categorias/salas)
        if self.proc and self.proc.state() == QProcess.ProcessState.Running:
            self.append_log("Cancelando execução...")

            # tenta encerrar de forma amigável
            self.proc.terminate()
            if not self.proc.waitForFinished(1500):
                self.append_log("Processo não encerrou a tempo; forçando encerramento (kill).")
                self.proc.kill()
                self.proc.waitForFinished(1500)

        self.queue = []
        self.current_step = ""
        self.proc = None

        self.append_log("Execução cancelada.")
        self.execute_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.exec_started = False

    def _start_next_step(self) -> None:
        if not self.queue:
            self.append_log("Execução finalizada (todos os passos concluídos).")
            self.execute_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.exec_started = False
            self.current_step = ""
            return

        step = self.queue.pop(0)
        self.current_step = step["name"]
        script = step["script"]
        args = step["args"]

        self.append_log(f"Iniciando passo: {self.current_step}")
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
        if not self.proc:
            self._start_next_step()
            return

        exit_code = self.proc.exitCode()
        if exit_code != 0:
            self.append_log(f"Passo '{self.current_step}' finalizou com erro (exit_code={exit_code}). Interrompendo.")
            self.execute_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.exec_started = False
            self.queue = []
            self.current_step = ""
            self.proc = None
            return

        self.append_log(f"Passo '{self.current_step}' concluído com sucesso.")
        self.proc = None
        self._start_next_step()

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