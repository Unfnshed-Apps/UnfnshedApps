"""
QAbstractListModel for the product inventory table.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QByteArray


class ProductInventoryModel(QAbstractListModel):
    SkuRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    StockRole = Qt.UserRole + 3
    LastUpdatedRole = Qt.UserRole + 4
    TargetStockRole = Qt.UserRole + 5
    VelocityRole = Qt.UserRole + 6
    StatusRole = Qt.UserRole + 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []  # list of dicts

    def roleNames(self):
        return {
            self.SkuRole: QByteArray(b"sku"),
            self.NameRole: QByteArray(b"name"),
            self.StockRole: QByteArray(b"stock"),
            self.LastUpdatedRole: QByteArray(b"lastUpdated"),
            self.TargetStockRole: QByteArray(b"targetStock"),
            self.VelocityRole: QByteArray(b"velocity"),
            self.StatusRole: QByteArray(b"stockStatus"),
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.SkuRole:
            return item.get("sku", "")
        if role == self.NameRole:
            return item.get("name", "")
        if role == self.StockRole:
            return item.get("stock", 0)
        if role == self.LastUpdatedRole:
            return item.get("last_updated", "")
        if role == self.TargetStockRole:
            return item.get("target_stock", 0)
        if role == self.VelocityRole:
            return item.get("velocity", 0.0)
        if role == self.StatusRole:
            return item.get("status", "adequate")
        return None

    def resetItems(self, items):
        """Replace all items. items is a list of dicts."""
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
