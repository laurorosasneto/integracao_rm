from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from ui_execution_tab import ExecutionTab
from ui_platforms_tab import PlatformsTab
from ui_rm_queries_tab import RMQueriesTab
from ui_rm_tab import RMTab
from ui_salas_modelo_tab import SalasModeloTab


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
        tabs.addTab(SalasModeloTab(), "Salas Modelo")
        tabs.addTab(ExecutionTab(), "Execução")

        layout = QVBoxLayout(root)
        layout.addWidget(header)
        layout.addWidget(tabs)