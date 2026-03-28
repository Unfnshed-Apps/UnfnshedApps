"""
QAbstractListModel for parts on a sheet — used in fallback spinbox mode.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, Slot


class PartsModel(QAbstractListModel):
    ComponentIdRole = Qt.UserRole + 1
    ComponentNameRole = Qt.UserRole + 2
    QuantityRole = Qt.UserRole + 3
    DamagedRole = Qt.UserRole + 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []  # list of dicts: {component_id, component_name, quantity, damaged}

    def roleNames(self):
        return {
            self.ComponentIdRole: b"componentId",
            self.ComponentNameRole: b"componentName",
            self.QuantityRole: b"quantity",
            self.DamagedRole: b"damaged",
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.ComponentIdRole:
            return item["component_id"]
        if role == self.ComponentNameRole:
            return item["component_name"]
        if role == self.QuantityRole:
            return item["quantity"]
        if role == self.DamagedRole:
            return item["damaged"]
        return None

    def resetItems(self, parts):
        """Reset with list of dicts: [{component_id, component_name, quantity}]"""
        self.beginResetModel()
        self._items = [
            {
                "component_id": p["component_id"],
                "component_name": p.get("component_name", f"Component #{p['component_id']}"),
                "quantity": p["quantity"],
                "damaged": 0,
            }
            for p in parts
        ]
        self.endResetModel()

    @Slot(int, int)
    def setDamaged(self, row, qty):
        if 0 <= row < len(self._items):
            self._items[row]["damaged"] = qty
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [self.DamagedRole])

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
