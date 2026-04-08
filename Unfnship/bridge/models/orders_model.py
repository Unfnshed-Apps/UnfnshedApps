"""
QAbstractListModel for the shipping order queue.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QByteArray


class OrdersModel(QAbstractListModel):
    OrderIdRole = Qt.UserRole + 1
    OrderNumberRole = Qt.UserRole + 2
    CustomerNameRole = Qt.UserRole + 3
    ItemCountRole = Qt.UserRole + 4
    ReadyToShipRole = Qt.UserRole + 5
    CreatedAtRole = Qt.UserRole + 6
    TotalPriceRole = Qt.UserRole + 7
    NoteRole = Qt.UserRole + 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def roleNames(self):
        return {
            self.OrderIdRole: QByteArray(b"orderId"),
            self.OrderNumberRole: QByteArray(b"orderNumber"),
            self.CustomerNameRole: QByteArray(b"customerName"),
            self.ItemCountRole: QByteArray(b"itemCount"),
            self.ReadyToShipRole: QByteArray(b"readyToShip"),
            self.CreatedAtRole: QByteArray(b"createdAt"),
            self.TotalPriceRole: QByteArray(b"totalPrice"),
            self.NoteRole: QByteArray(b"note"),
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.OrderIdRole:
            return item.get("order_id", 0)
        if role == self.OrderNumberRole:
            return item.get("name", "")
        if role == self.CustomerNameRole:
            return item.get("customer_name", "")
        if role == self.ItemCountRole:
            return len(item.get("items", []))
        if role == self.ReadyToShipRole:
            return item.get("ready_to_ship", False)
        if role == self.CreatedAtRole:
            created = item.get("created_at", "")
            if created and "T" in str(created):
                return str(created).split("T")[0]
            return str(created) if created else ""
        if role == self.TotalPriceRole:
            return item.get("total_price", "0.00")
        if role == self.NoteRole:
            return item.get("note", "")
        return None

    def resetItems(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
