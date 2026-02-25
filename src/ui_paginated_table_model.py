from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


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
