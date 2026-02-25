from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QComboBox,
)

from ui_paginated_table_model import PaginatedTableModel


class QueryResultDialog(QDialog):
    def __init__(self, parent, columns: list[str], rows: list[tuple]) -> None:
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
