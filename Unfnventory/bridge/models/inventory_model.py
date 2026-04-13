"""
QAbstractListModel for the inventory table.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QByteArray


class InventoryListModel(QAbstractListModel):
    ComponentIdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    DxfFilenameRole = Qt.UserRole + 3
    StockRole = Qt.UserRole + 4
    LastUpdatedRole = Qt.UserRole + 5
    TargetStockRole = Qt.UserRole + 6
    VelocityRole = Qt.UserRole + 7
    PipelineRole = Qt.UserRole + 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []  # list of dicts

    def roleNames(self):
        return {
            self.ComponentIdRole: QByteArray(b"componentId"),
            self.NameRole: QByteArray(b"name"),
            self.DxfFilenameRole: QByteArray(b"dxfFilename"),
            self.StockRole: QByteArray(b"stock"),
            self.LastUpdatedRole: QByteArray(b"lastUpdated"),
            self.TargetStockRole: QByteArray(b"targetStock"),
            self.VelocityRole: QByteArray(b"velocity"),
            self.PipelineRole: QByteArray(b"pipeline"),
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
        if role == self.StockRole:
            return item["stock"]
        if role == self.LastUpdatedRole:
            return item["last_updated"]
        if role == self.TargetStockRole:
            return item.get("target_stock", 0)
        if role == self.VelocityRole:
            return item.get("velocity", 0.0)
        if role == self.PipelineRole:
            return item.get("pipeline", 0)
        return None

    def resetItems(self, items):
        """Replace all items, preserving scroll position when possible.

        If the row count is unchanged, emit dataChanged instead of a full
        model reset so QML keeps the ListView scroll position.
        """
        new_items = list(items)
        if len(new_items) == len(self._items):
            self._items = new_items
            if new_items:
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(len(new_items) - 1, 0),
                    list(self.roleNames().keys()),
                )
        else:
            self.beginResetModel()
            self._items = new_items
            self.endResetModel()

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
