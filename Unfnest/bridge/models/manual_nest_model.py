"""
QAbstractListModel for the manual nests table.

Each item represents one manual nest as returned by /manual-nests:
    {
        "id": int,
        "name": str,
        "override_enabled": bool,
        "sheets": list of sheet dicts (each with parts),
        ...
    }

The model exposes derived fields — a compact "SKU: qty" summary for the row
display and a sheet count — computed from the nested parts.
"""

from collections import Counter

from PySide6.QtCore import Qt, QAbstractListModel, QByteArray, QModelIndex


def _summarize_parts(sheets: list[dict]) -> str:
    """Build a human-readable summary of product SKUs and their unit counts
    across all sheets of a manual nest. Returns e.g. 'BENCH-01 x2, SHELF-03 x1'
    or a fallback when no product SKUs are present (e.g. loose components)."""
    unit_counter: Counter = Counter()
    loose_count = 0
    for sheet in sheets or []:
        for part in sheet.get("parts", []) or []:
            sku = part.get("product_sku")
            unit = part.get("product_unit")
            if sku is not None and unit is not None:
                unit_counter[(sku, unit)] += 1
            else:
                loose_count += 1

    # Collapse (sku, unit) pairs into {sku: distinct_units}
    by_sku: dict[str, set[int]] = {}
    for (sku, unit) in unit_counter:
        by_sku.setdefault(sku, set()).add(unit)

    parts: list[str] = []
    for sku in sorted(by_sku):
        n = len(by_sku[sku])
        parts.append(f"{sku} x{n}")
    if loose_count:
        parts.append(f"{loose_count} loose")
    return ", ".join(parts) if parts else "(empty)"


class ManualNestListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    OverrideEnabledRole = Qt.UserRole + 3
    SummaryRole = Qt.UserRole + 4
    SheetCountRole = Qt.UserRole + 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []

    def roleNames(self):
        return {
            self.IdRole: QByteArray(b"nestId"),
            self.NameRole: QByteArray(b"name"),
            self.OverrideEnabledRole: QByteArray(b"overrideEnabled"),
            self.SummaryRole: QByteArray(b"summary"),
            self.SheetCountRole: QByteArray(b"sheetCount"),
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.IdRole:
            return int(item.get("id", 0))
        if role == self.NameRole:
            return item.get("name", "")
        if role == self.OverrideEnabledRole:
            return bool(item.get("override_enabled", False))
        if role == self.SummaryRole:
            return _summarize_parts(item.get("sheets") or [])
        if role == self.SheetCountRole:
            return len(item.get("sheets") or [])
        return None

    def setData(self, index, value, role=Qt.EditRole):
        """Allow QML-side override toggles to update the model optimistically.

        The controller still sends the server the authoritative PUT; this keeps
        the UI responsive while that round-trip happens.
        """
        if not index.isValid() or index.row() >= len(self._items):
            return False
        if role == self.OverrideEnabledRole:
            self._items[index.row()]["override_enabled"] = bool(value)
            self.dataChanged.emit(index, index, [self.OverrideEnabledRole])
            return True
        return False

    def flags(self, index):
        return super().flags(index) | Qt.ItemIsEditable

    def resetItems(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
