"""
QAbstractListModel for the orders table.
"""

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QByteArray


class OrderListModel(QAbstractListModel):
    OrderNumberRole = Qt.UserRole + 1
    CustomerNameRole = Qt.UserRole + 2
    SkusRole = Qt.UserRole + 3
    TotalRole = Qt.UserRole + 4
    ShopifyStatusRole = Qt.UserRole + 5
    ProductionStatusRole = Qt.UserRole + 6
    CreatedAtRole = Qt.UserRole + 7
    StatusColorRole = Qt.UserRole + 8
    # New roles
    EmailRole = Qt.UserRole + 9
    PhoneRole = Qt.UserRole + 10
    SubtotalPriceRole = Qt.UserRole + 11
    TotalTaxRole = Qt.UserRole + 12
    TotalDiscountsRole = Qt.UserRole + 13
    TotalShippingRole = Qt.UserRole + 14
    FinancialStatusRole = Qt.UserRole + 15
    NoteRole = Qt.UserRole + 16
    TagsRole = Qt.UserRole + 17
    SourceNameRole = Qt.UserRole + 18
    ShopifyOrderIdRole = Qt.UserRole + 19
    DisplayNameRole = Qt.UserRole + 20
    NestedAtRole = Qt.UserRole + 21
    CutAtRole = Qt.UserRole + 22
    PackedAtRole = Qt.UserRole + 23
    SyncedAtRole = Qt.UserRole + 24
    ProcessedAtRole = Qt.UserRole + 25
    CancelledAtRole = Qt.UserRole + 26
    CancelReasonRole = Qt.UserRole + 27
    ClosedAtRole = Qt.UserRole + 28
    ShippingAddressRole = Qt.UserRole + 29
    BillingAddressRole = Qt.UserRole + 30
    DiscountCodesRole = Qt.UserRole + 31
    ShippingMethodRole = Qt.UserRole + 32
    PaymentMethodRole = Qt.UserRole + 33
    LandingSiteRole = Qt.UserRole + 34
    ReferringSiteRole = Qt.UserRole + 35

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []  # list of dicts

    def roleNames(self):
        return {
            self.OrderNumberRole: QByteArray(b"orderNumber"),
            self.CustomerNameRole: QByteArray(b"customerName"),
            self.SkusRole: QByteArray(b"skus"),
            self.TotalRole: QByteArray(b"total"),
            self.ShopifyStatusRole: QByteArray(b"shopifyStatus"),
            self.ProductionStatusRole: QByteArray(b"productionStatus"),
            self.CreatedAtRole: QByteArray(b"createdAt"),
            self.StatusColorRole: QByteArray(b"statusColor"),
            self.EmailRole: QByteArray(b"email"),
            self.PhoneRole: QByteArray(b"phone"),
            self.SubtotalPriceRole: QByteArray(b"subtotalPrice"),
            self.TotalTaxRole: QByteArray(b"totalTax"),
            self.TotalDiscountsRole: QByteArray(b"totalDiscounts"),
            self.TotalShippingRole: QByteArray(b"totalShipping"),
            self.FinancialStatusRole: QByteArray(b"financialStatus"),
            self.NoteRole: QByteArray(b"note"),
            self.TagsRole: QByteArray(b"tags"),
            self.SourceNameRole: QByteArray(b"sourceName"),
            self.ShopifyOrderIdRole: QByteArray(b"shopifyOrderId"),
            self.DisplayNameRole: QByteArray(b"displayName"),
            self.NestedAtRole: QByteArray(b"nestedAt"),
            self.CutAtRole: QByteArray(b"cutAt"),
            self.PackedAtRole: QByteArray(b"packedAt"),
            self.SyncedAtRole: QByteArray(b"syncedAt"),
            self.ProcessedAtRole: QByteArray(b"processedAt"),
            self.CancelledAtRole: QByteArray(b"cancelledAt"),
            self.CancelReasonRole: QByteArray(b"cancelReason"),
            self.ClosedAtRole: QByteArray(b"closedAt"),
            self.ShippingAddressRole: QByteArray(b"shippingAddress"),
            self.BillingAddressRole: QByteArray(b"billingAddress"),
            self.DiscountCodesRole: QByteArray(b"discountCodes"),
            self.ShippingMethodRole: QByteArray(b"shippingMethod"),
            self.PaymentMethodRole: QByteArray(b"paymentMethod"),
            self.LandingSiteRole: QByteArray(b"landingSite"),
            self.ReferringSiteRole: QByteArray(b"referringSite"),
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.OrderNumberRole:
            return item["orderNumber"]
        if role == self.CustomerNameRole:
            return item["customerName"]
        if role == self.SkusRole:
            return item["skus"]
        if role == self.TotalRole:
            return item["total"]
        if role == self.ShopifyStatusRole:
            return item["shopifyStatus"]
        if role == self.ProductionStatusRole:
            return item["productionStatus"]
        if role == self.CreatedAtRole:
            return item["createdAt"]
        if role == self.StatusColorRole:
            return item["statusColor"]
        if role == self.EmailRole:
            return item.get("email", "")
        if role == self.PhoneRole:
            return item.get("phone", "")
        if role == self.SubtotalPriceRole:
            return item.get("subtotalPrice", "")
        if role == self.TotalTaxRole:
            return item.get("totalTax", "")
        if role == self.TotalDiscountsRole:
            return item.get("totalDiscounts", "")
        if role == self.TotalShippingRole:
            return item.get("totalShipping", "")
        if role == self.FinancialStatusRole:
            return item.get("financialStatus", "")
        if role == self.NoteRole:
            return item.get("note", "")
        if role == self.TagsRole:
            return item.get("tags", "")
        if role == self.SourceNameRole:
            return item.get("sourceName", "")
        if role == self.ShopifyOrderIdRole:
            return item.get("shopifyOrderId", "")
        if role == self.DisplayNameRole:
            return item.get("displayName", "")
        if role == self.NestedAtRole:
            return item.get("nestedAt", "")
        if role == self.CutAtRole:
            return item.get("cutAt", "")
        if role == self.PackedAtRole:
            return item.get("packedAt", "")
        if role == self.SyncedAtRole:
            return item.get("syncedAt", "")
        if role == self.ProcessedAtRole:
            return item.get("processedAt", "")
        if role == self.CancelledAtRole:
            return item.get("cancelledAt", "")
        if role == self.CancelReasonRole:
            return item.get("cancelReason", "")
        if role == self.ClosedAtRole:
            return item.get("closedAt", "")
        if role == self.ShippingAddressRole:
            return item.get("shippingAddress", "")
        if role == self.BillingAddressRole:
            return item.get("billingAddress", "")
        if role == self.DiscountCodesRole:
            return item.get("discountCodes", "")
        if role == self.ShippingMethodRole:
            return item.get("shippingMethod", "")
        if role == self.PaymentMethodRole:
            return item.get("paymentMethod", "")
        if role == self.LandingSiteRole:
            return item.get("landingSite", "")
        if role == self.ReferringSiteRole:
            return item.get("referringSite", "")
        return None

    def resetItems(self, items):
        """Replace all items. items is a list of dicts."""
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def appendItems(self, items):
        """Append items to the end of the list."""
        if not items:
            return
        start = len(self._items)
        self.beginInsertRows(QModelIndex(), start, start + len(items) - 1)
        self._items.extend(items)
        self.endInsertRows()

    def getItemAtRow(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None
