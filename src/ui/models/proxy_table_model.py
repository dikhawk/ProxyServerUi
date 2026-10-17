"""Table model for displaying proxy items in QTableView."""
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from src.domain.enums import ProxyStatus
from src.domain.proxy_item import ProxyItem


class ProxyTableModel(QAbstractTableModel):
    """QAbstractTableModel implementation for ProxyItem items."""

    COLUMNS = (
        "Тип",
        "Адрес",
        "Локация",
        "Статус",
        "Пинг",
        "URL Статус",
        "Добавлен",
        "Сбои",
        "Мертв с",
    )

    def __init__(self, items: list[ProxyItem] | None = None, max_attempts: int = 5) -> None:
        super().__init__()
        self._items: list[ProxyItem] = list(items or [])
        self.max_attempts = max_attempts

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self.COLUMNS)
        ):
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None

        item = self._items[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return item.protocol.value
            if col == 1:
                return f"{item.host}:{item.port}"
            if col == 2:
                return item.location
            if col == 3:
                return item.status.value
            if col == 4:
                return f"{item.ping}ms" if item.ping is not None else "-"
            if col == 5:
                return item.url_status
            if col == 6:
                return item.added_at
            if col == 7:
                return f"{item.fail_count}/{self.max_attempts}"
            if col == 8:
                return item.dead_since if item.dead_since else "-"

        if role == Qt.ItemDataRole.UserRole:
            # Raw values for sorting in ProxySortFilterModel
            if col == 4:
                return item.ping if item.ping is not None else 999999
            if col == 7:
                return item.fail_count
            if col == 0:
                return item.protocol.value
            if col == 1:
                return f"{item.host}:{item.port}"
            if col == 2:
                return item.location
            if col == 3:
                return item.status.value
            if col == 6:
                return item.added_at
            if col == 8:
                return item.dead_since

        if role == Qt.ItemDataRole.ForegroundRole and col == 3:
            if item.status == ProxyStatus.ACTIVE:
                return QColor("#2ecc71")
            if item.status == ProxyStatus.DEAD:
                return QColor("#e74c3c")
            if item.status == ProxyStatus.CHECKING:
                return QColor("#f39c12")
            if item.status == ProxyStatus.UNTESTED:
                return QColor("#95a5a6")

        return None

    def set_proxies(self, items: list[ProxyItem]) -> None:
        """Replace all items in model and reset view."""
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def set_max_attempts(self, max_attempts: int) -> None:
        """Update max dead attempts threshold and notify view to re-render failure column."""
        self.max_attempts = max_attempts
        if self._items:
            top_left = self.index(0, 7)
            bottom_right = self.index(len(self._items) - 1, 7)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])

    def update_proxy(self, item: ProxyItem) -> None:
        """Find row by unique key and emit dataChanged to refresh UI."""
        target_key = item.unique_key
        for row, it in enumerate(self._items):
            if it.unique_key == target_key:
                top_left = self.index(row, 0)
                bottom_right = self.index(row, len(self.COLUMNS) - 1)
                self.dataChanged.emit(top_left, bottom_right)
                break

    def get_proxy(self, row: int) -> ProxyItem | None:
        """Retrieve ProxyItem by row index."""
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
