"""
QAbstractListModel for the machines table.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QByteArray


class MachineListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    ActiveRole = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def roleNames(self):
        return {
            self.IdRole: QByteArray(b"machineId"),
            self.NameRole: QByteArray(b"name"),
            self.ActiveRole: QByteArray(b"active"),
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.IdRole:
            return item["id"]
        if role == self.NameRole:
            return item["name"]
        if role == self.ActiveRole:
            return item["active"]
        return None

    def resetItems(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
