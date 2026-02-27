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


class EnsalamentoTab(QWidget):
    """Aba Ensalamento.

    Regras do combo Período (pedido):
    - Ao selecionar uma plataforma, listar TODOS os períodos (IDPERLET) das coligadas dessa plataforma.
    - Exibir no combo a coluna LABELPERIODO (label humano).
    - O valor do item (currentData) deve ser o IDPERLET selecionado.

    Observação importante:
    - A query rm_queries.periodos precisa expor pelo menos: CODCOLIGADA, IDPERLET e LABELPERIODO.
    """

    def __init__(self) -> None:
        super().__init__()

        self.proc: QProcess | None = None
        self.timer = QElapsedTimer()

        title = QLabel("Ensalamento")
        title.setObjectName("TabTitle")

        subtitle = QLabel("Executa o ensalamento/matrícula (alunos e professores) no Moodle a partir de SQL do RM.")
        subtitle.setObjectName("TabSubtitle")

        self.platform_combo = QComboBox()
        self.platform_combo.setObjectName("Select")
        self.platform_combo.currentIndexChanged.connect(self.on_platform_changed)

        self.period_combo = LazyComboBox()
        self.period_combo.setObjectName("Select")
        self.period_combo.set_loader(self.populate_periodos)

        self.chk_alunos = QCheckBox("Ensalamento Alunos")
        self.chk_alunos.setChecked(True)

        self.chk_professores = QCheckBox("Ensalamento Professores")
        self.chk_professores.setChecked(False)

        # Debug: habilita logs detalhados do WS e, no caso de PROFESSORES,
        # imprime APENAS o SQL final usado para filtrar (pedido do projeto).
        self.chk_debug_ws = QCheckBox("Debug (mostrar SQL/WS)")
        self.chk_debug_ws.setChecked(True)

        self.run_btn = QPushButton("Executar")
        self.run_btn.setObjectName("ExecuteButton")
        self.run_btn.clicked.connect(self.on_run)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("CancelButton")
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.cancel_btn.setEnabled(False)

        self.debug = QPlainTextEdit()
        self.debug.setObjectName("Terminal")
        self.debug.setReadOnly(True)
        self.debug.setPlaceholderText("Logs de execução aparecerão aqui...")

        form = QFrame()
        form.setObjectName("FormCard")
        form_layout = QFormLayout(form)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        form_layout.addRow("Plataforma", self.platform_combo)
        form_layout.addRow("Período", self.period_combo)
        form_layout.addRow("", self.chk_alunos)
        form_layout.addRow("", self.chk_professores)
        form_layout.addRow("", self.chk_debug_ws)

        actions = QHBoxLayout()
        actions.addWidget(self.run_btn)
        actions.addWidget(self.cancel_btn)
        actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(form)
        layout.addLayout(actions)
        layout.addWidget(self.debug)

        self.load_platforms()
        self.on_platform_changed()

    def append_log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.debug.appendPlainText(f"[{ts}] {msg}")

    def load_platforms(self) -> None:
        self.platform_combo.clear()
        items = list_platforms_for_select()
        self.platform_combo.addItem("Selecione...", None)
        for pid, name in items:
            self.platform_combo.addItem(name, pid)

    def on_platform_changed(self) -> None:
        self.period_combo.clear()
        self.period_combo.addItem("Todos", "")
        self.period_combo.reset_loaded()

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
        """Ordena por ano/termo quando o label começar com YYYY..."""
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

    def populate_periodos(self) -> None:
        """Carrega períodos filtrando por coligadas da plataforma.

        - Exibe LABELPERIODO no combo
        - currentData = IDPERLET
        - Lista TODOS os IDPERLET (sem dedup por CATPERIODO)
        """
        self.period_combo.clear()
        self.period_combo.addItem("Todos", "")

        platform_id = self.platform_combo.currentData()
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

        queries = get_rm_queries() or {}
        config = get_rm_config()
        base_sql = (queries.get("periodos") or "").strip()
        if not base_sql or not config:
            self.append_log("Consulta/config do RM ausente; não carregando períodos.")
            return

        base_sql = self._strip_sql(base_sql)
        base_no_order = self._remove_last_order_by(base_sql)
        in_list = self._sql_in_list(allowed)
        if not in_list:
            self.append_log("Lista de coligadas inválida (IN vazio); não carregando períodos.")
            return

        # Wrapper: filtra por CODCOLIGADA.
        # Sua query atual retorna LABELPERIODO (sem underscore).
        sql = (
            "SELECT X.CODCOLIGADA, X.IDPERLET, X.LABELPERIODO "
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
        idx_idperlet = idx("idperlet")

        # Aceita vários nomes possíveis para o label (mas o seu é LABELPERIODO)
        idx_label = idx("labelperiodo")
        if idx_label is None:
            idx_label = idx("label_periodo")
        if idx_label is None:
            idx_label = idx("label")

        if idx_codcol is None or idx_idperlet is None or idx_label is None:
            self.append_log("SQL de períodos deve retornar: CODCOLIGADA, IDPERLET e LABELPERIODO.")
            return

        # Lista TODOS os IDPERLET (um item por IDPERLET)
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

            # Mantém o primeiro label não-vazio (ou substitui fallback por um label real)
            if idperlet not in by_id:
                by_id[idperlet] = label
            else:
                if by_id[idperlet].startswith("IDPERLET ") and not label.startswith("IDPERLET "):
                    by_id[idperlet] = label

        if not by_id:
            self.append_log("Nenhum período encontrado após filtragem por coligadas.")
            return

        items = sorted(by_id.items(), key=lambda kv: (self._period_sort_key(kv[1]), kv[0]), reverse=True)

        for idperlet, label in items:
            self.period_combo.addItem(label, str(idperlet))

        self.append_log(f"Períodos adicionados (por IDPERLET): {len(items)}")

    def _lock_ui(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.platform_combo.setEnabled(not running)
        self.period_combo.setEnabled(not running)
        self.chk_alunos.setEnabled(not running)
        self.chk_professores.setEnabled(not running)
        self.chk_debug_ws.setEnabled(not running)

    def on_run(self) -> None:
        pid = self.platform_combo.currentData()
        if not pid:
            QMessageBox.warning(self, "Plataforma", "Selecione uma plataforma.")
            return

        queries = get_rm_queries() or {}
        if not (queries.get("ensalamento_alunos") or "").strip() and self.chk_alunos.isChecked():
            QMessageBox.warning(self, "Consulta ausente", "A consulta 'Ensalamento Alunos' está vazia (aba Consultas RM).")
            return
        if not (queries.get("ensalamento_professores") or "").strip() and self.chk_professores.isChecked():
            QMessageBox.warning(
                self,
                "Consulta ausente",
                "A consulta 'Ensalamento Professores' está vazia (aba Consultas RM).",
            )
            return
        if not self.chk_alunos.isChecked() and not self.chk_professores.isChecked():
            QMessageBox.warning(self, "Opções", "Marque pelo menos uma opção de ensalamento.")
            return

        idperlet = self.period_combo.currentData() or ""

        script_path = Path(__file__).resolve().parent / "ensalamento.py"
        if not script_path.exists():
            QMessageBox.critical(self, "Arquivo ausente", f"Script não encontrado: {script_path}")
            return

        args = [
            sys.executable,
            str(script_path),
            "--platform-id",
            str(int(pid)),
            "--idperlet",
            str(idperlet),
            "--ensalamento-alunos",
            "1" if self.chk_alunos.isChecked() else "0",
            "--ensalamento-professores",
            "1" if self.chk_professores.isChecked() else "0",
            "--debug-ws",
            "1" if self.chk_debug_ws.isChecked() else "0",
        ]

        self.debug.clear()
        self.append_log("Iniciando ensalamento (filtros automáticos: coligada + IDPERLET)...")

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._on_proc_output)
        self.proc.finished.connect(self._on_proc_finished)

        self.timer.start()
        self.proc.start(args[0], args[1:])

        self._lock_ui(True)

    def on_cancel(self) -> None:
        if self.proc and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.append_log("Cancelando processo...")
            self.proc.kill()

    def _on_proc_output(self) -> None:
        if not self.proc:
            return
        data = bytes(self.proc.readAllStandardOutput())
        text = self._decode_output(data)
        for line in text.splitlines():
            line = line.rstrip()
            if line:
                self.debug.appendPlainText(line)

    def _on_proc_finished(self) -> None:
        elapsed_ms = self.timer.elapsed()
        elapsed_s = max(0.0, elapsed_ms / 1000.0)

        self._lock_ui(False)
        self.append_log(f"Processo finalizado em {elapsed_s:.1f}s.")

        full = self.debug.toPlainText()
        resumo = ""
        for line in full.splitlines()[::-1]:
            if line.startswith("RESUMO_FINAL:"):
                resumo = line.replace("RESUMO_FINAL:", "").strip()
                break

        if resumo:
            QMessageBox.information(self, "Concluído", resumo)
        else:
            QMessageBox.information(self, "Concluído", "Processo de ensalamento concluído.")
