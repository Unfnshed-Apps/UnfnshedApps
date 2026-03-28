"""
QAbstractListModel for the products table.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QByteArray


class ProductListModel(QAbstractListModel):
    SkuRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    ComponentSummaryRole = Qt.UserRole + 3
    QuantityRole = Qt.UserRole + 4
    OutsourcedRole = Qt.UserRole + 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._quantities = {}  # sku -> qty

    def roleNames(self):
        return {
            self.SkuRole: QByteArray(b"sku"),
            self.NameRole: QByteArray(b"name"),
            self.ComponentSummaryRole: QByteArray(b"componentSummary"),
            self.QuantityRole: QByteArray(b"quantity"),
            self.OutsourcedRole: QByteArray(b"outsourced"),
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.SkuRole:
            return item["sku"]
        if role == self.NameRole:
            return item["name"]
        if role == self.ComponentSummaryRole:
            return item["component_summary"]
        if role == self.QuantityRole:
            return self._quantities.get(item["sku"], 0)
        if role == self.OutsourcedRole:
            return item.get("outsourced", False)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or index.row() >= len(self._items):
            return False
        if role == self.QuantityRole:
            item = self._items[index.row()]
            self._quantities[item["sku"]] = int(value)
            self.dataChanged.emit(index, index, [self.QuantityRole])
            return True
        return False

    def flags(self, index):
        return super().flags(index) | Qt.ItemIsEditable

    def resetItems(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def clearQuantities(self):
        self.beginResetModel()
        self._quantities.clear()
        self.endResetModel()

    def getQuantities(self):
        return {sku: qty for sku, qty in self._quantities.items() if qty > 0}

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
