"""Sort and filter proxy model for proper numeric and string sorting."""
from PyQt6.QtCore import QModelIndex, QSortFilterProxyModel, Qt


class ProxySortFilterModel(QSortFilterProxyModel):
    """Custom QSortFilterProxyModel ensuring correct numeric comparisons for ping and failures."""

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return super().lessThan(left, right)

        left_val = model.data(left, Qt.ItemDataRole.UserRole)
        right_val = model.data(right, Qt.ItemDataRole.UserRole)

        if left_val is None and right_val is None:
            return False
        if left_val is None:
            return True
        if right_val is None:
            return False

        if isinstance(left_val, (int, float)) and isinstance(right_val, (int, float)):
            return left_val < right_val

        return str(left_val).lower() < str(right_val).lower()
