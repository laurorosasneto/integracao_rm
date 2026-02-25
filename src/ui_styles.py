from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication


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
