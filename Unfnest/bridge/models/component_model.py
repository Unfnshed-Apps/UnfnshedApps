"""
QAbstractListModel for the components table.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QByteArray


class ComponentListModel(QAbstractListModel):
    ComponentIdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    DxfFilenameRole = Qt.UserRole + 3
    QuantityRole = Qt.UserRole + 4
    HasGeometryRole = Qt.UserRole + 5
    VariablePocketsRole = Qt.UserRole + 6
    InventoryCountRole = Qt.UserRole + 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []  # list of dicts
        self._quantities = {}  # component_id -> qty

    def roleNames(self):
        return {
            self.ComponentIdRole: QByteArray(b"componentId"),
            self.NameRole: QByteArray(b"name"),
            self.DxfFilenameRole: QByteArray(b"dxfFilename"),
            self.QuantityRole: QByteArray(b"quantity"),
            self.HasGeometryRole: QByteArray(b"hasGeometry"),
            self.VariablePocketsRole: QByteArray(b"variablePockets"),
            self.InventoryCountRole: QByteArray(b"inventoryCount"),
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.ComponentIdRole:
            return item["id"]
        if role == self.NameRole:
            return item["name"]
        if role == self.DxfFilenameRole:
            return item["dxf_filename"]
        if role == self.QuantityRole:
            return self._quantities.get(item["id"], 0)
        if role == self.HasGeometryRole:
            return item.get("has_geometry", False)
        if role == self.VariablePocketsRole:
            return item.get("variable_pockets", False)
        if role == self.InventoryCountRole:
            return item.get("inventory_count", 0)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or index.row() >= len(self._items):
            return False
        if role == self.QuantityRole:
            item = self._items[index.row()]
            self._quantities[item["id"]] = int(value)
            self.dataChanged.emit(index, index, [self.QuantityRole])
            return True
        return False

    def flags(self, index):
        return super().flags(index) | Qt.ItemIsEditable

    def resetItems(self, items):
        """Replace all items. items is a list of dicts."""
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def clearQuantities(self):
        self.beginResetModel()
        self._quantities.clear()
        self.endResetModel()

    def getQuantities(self):
        """Return dict of component_id -> quantity for non-zero entries."""
        return {cid: qty for cid, qty in self._quantities.items() if qty > 0}

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
