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
    """Aba Inserção de Pessoas.

    Regras implementadas:
    - Combo Período lista LABELPERIODO e guarda IDPERLET como value.
    - Ao trocar plataforma, o combo recarrega e filtra por CODCOLIGADA IN (<coligadas da plataforma>).
    - Checkbox "Debug (mostrar SQL/WS)": quando marcado, passa --debug-ws=1 ao script.
      O script imprime APENAS o SQL final (sem rótulos) para ALUNOS e PROFESSORES.
    """

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

        self.chk_debug_sql = QCheckBox("Debug (mostrar SQL/WS)")
        self.chk_debug_sql.setChecked(True)

        form_layout.addRow("Plataforma", self.platform_select)
        form_layout.addRow("Período", self.periodo_select)
        form_layout.addRow("", self.chk_alunos)
        form_layout.addRow("", self.chk_professores)
        form_layout.addRow("", self.chk_debug_sql)

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
        self.on_platform_changed()

    # -----------------
    # Helpers
    # -----------------
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

    def _period_sort_key(self, label: str) -> tuple[int, int, str]:
        # tenta ordenar por ANO/TERMO extraindo números do início do label
        s = (label or "").strip()
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

    # -----------------
    # Platform / Period
    # -----------------
    def load_platforms(self) -> None:
        self.platform_select.clear()
        items = list_platforms_for_select()
        self.platform_select.addItem("Selecione...", None)
        for platform_id, name in items:
            self.platform_select.addItem(name, platform_id)

    def on_platform_changed(self) -> None:
        self.periodo_select.clear()
        self.periodo_select.addItem("Todos", "")
        self.periodo_select.reset_loaded()

    def populate_periodos(self) -> None:
        """Carrega períodos para a plataforma selecionada.

        - Exibe LABELPERIODO
        - Valor (data) é IDPERLET
        - Filtra automaticamente por CODCOLIGADA IN (<coligadas da plataforma>)

        Requisito: rm_queries.periodos deve retornar (no mínimo):
        CODCOLIGADA, IDPERLET e LABELPERIODO.
        """

        self.periodo_select.clear()
        self.periodo_select.addItem("Todos", "")

        platform_id = self.platform_select.currentData()
        if platform_id is None:
            self.append_log("Nenhuma plataforma selecionada; não carregando períodos.")
            return

        rm_cfg = get_rm_config()
        if not rm_cfg:
            self.append_log("Config do RM ausente; não carregando períodos.")
            return

        col_csv = get_platform_coligadas(int(platform_id)) or ""
        allowed = {self._norm(c) for c in col_csv.split(",") if self._norm(c)}
        if not allowed:
            self.append_log("Plataforma não tem coligadas selecionadas; não carregando períodos.")
            return

        queries = get_rm_queries() or {}
        base_sql = (queries.get("periodos") or "").strip()
        if not base_sql:
            self.append_log("Consulta de períodos (rm_queries.periodos) vazia; não carregando períodos.")
            return

        base_sql = self._strip_sql(base_sql)
        base_no_order = self._remove_last_order_by(base_sql)
        in_list = self._sql_in_list(allowed)
        if not in_list:
            self.append_log("Lista de coligadas inválida (IN vazio); não carregando períodos.")
            return

        # Wrapper para garantir filtro por coligada, independente do SQL base.
        sql = (
            "SELECT X.CODCOLIGADA, X.IDPERLET, X.LABELPERIODO "
            "FROM (" + base_no_order + ") X "
            f"WHERE X.CODCOLIGADA IN ({in_list})"
        )

        host, db_name, username, password = rm_cfg
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
        idx_idperlet = idx("idperlet")
        idx_label = idx("labelperiodo")

        if idx_codcol is None or idx_idperlet is None or idx_label is None:
            self.append_log("SQL de períodos deve retornar: CODCOLIGADA, IDPERLET, LABELPERIODO.")
            return

        by_id: dict[int, str] = {}

        for row in rows:
            codcol = self._norm(row[idx_codcol])
            if not codcol or codcol not in allowed:
                continue

            idperlet_str = self._norm(row[idx_idperlet])
            if not idperlet_str or not idperlet_str.isdigit():
                continue
            idperlet = int(idperlet_str)

            label = "" if row[idx_label] is None else str(row[idx_label]).strip()
            if not label:
                label = f"IDPERLET {idperlet}"

            # 1 item por IDPERLET
            if idperlet not in by_id:
                by_id[idperlet] = label
            else:
                # melhora label se a anterior era fallback
                if by_id[idperlet].startswith("IDPERLET ") and not label.startswith("IDPERLET "):
                    by_id[idperlet] = label

        if not by_id:
            self.append_log("Nenhum período encontrado após filtragem por coligadas.")
            return

        items = sorted(by_id.items(), key=lambda kv: (self._period_sort_key(kv[1]), kv[0]), reverse=True)
        for idperlet, label in items:
            self.periodo_select.addItem(label, str(idperlet))

        self.append_log(f"Períodos adicionados (por IDPERLET): {len(items)}")

    # -----------------
    # Execution
    # -----------------
    def on_execute(self) -> None:
        if self.proc and self.proc.state() == QProcess.ProcessState.Running:
            QMessageBox.information(self, "Inserção de Pessoas", "Já existe uma execução em andamento.")
            return

        platform_id = self.platform_select.currentData()
        if platform_id is None:
            QMessageBox.warning(self, "Plataforma obrigatória", "Selecione uma plataforma.")
            return

        idperlet = (self.periodo_select.currentData() or "").strip()

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
            "--idperlet",
            idperlet,
            "--debug-ws",
            "1" if self.chk_debug_sql.isChecked() else "0",
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

        # Mantém padrão do terminal (sem mexer em prefixos do script)
        self.log.appendPlainText(prefix + text)