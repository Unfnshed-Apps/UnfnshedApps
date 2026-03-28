"""
Order controller — filtered orders list with infinite scroll pagination via API client.
"""

from PySide6.QtCore import QObject, Property, Signal, Slot

from bridge.models.order_model import OrderListModel

PAGE_SIZE = 200

FILTER_OPTIONS = [
    "All Orders",
    "Pending",
    "Nested",
    "Cut",
    "Shipped",
    "Unfulfilled (Shopify)",
]

STATUS_COLORS = {
    "pending": "",
    "nested": "#2196F3",
    "cut": "#00897B",
    "completed": "#4CAF50",
    "shipped": "#4CAF50",
}

# Map display filter text to API filter parameter
FILTER_MAP = {
    "All Orders": "all",
    "Pending": "pending",
    "Nested": "nested",
    "Cut": "cut",
    "Shipped": "shipped",
    "Unfulfilled (Shopify)": "unfulfilled",
}


class OrderController(QObject):
    orderCountChanged = Signal()
    totalCountChanged = Signal()
    canLoadMoreChanged = Signal()
    statusMessage = Signal(str, int)
    operationFailed = Signal(str)

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = OrderListModel(self)
        self._filter = "All Orders"
        self._order_count = 0
        self._total_count = 0
        self._can_load_more = False
        self._offset = 0

    # ── Properties ──────────────────────────────────────────────

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property(int, notify=orderCountChanged)
    def orderCount(self):
        return self._order_count

    @Property(int, notify=totalCountChanged)
    def totalCount(self):
        return self._total_count

    @Property(bool, notify=canLoadMoreChanged)
    def canLoadMore(self):
        return self._can_load_more

    @Property("QVariantList", constant=True)
    def filterOptions(self):
        return FILTER_OPTIONS

    # ── Slots ───────────────────────────────────────────────────

    @Slot()
    def refresh(self):
        """Reset and load first page."""
        self._offset = 0
        self._fetch_total_count()
        items = self._fetch_page(0)
        self._model.resetItems(items)
        self._offset = len(items)
        self._order_count = len(items)
        self.orderCountChanged.emit()
        self._update_can_load_more()

    @Slot()
    def loadMore(self):
        """Load next page and append to existing list."""
        if not self._can_load_more:
            return
        items = self._fetch_page(self._offset)
        if items:
            self._model.appendItems(items)
            self._offset += len(items)
            self._order_count = self._offset
            self.orderCountChanged.emit()
        self._update_can_load_more()

    @Slot(str)
    def setFilter(self, filter_text):
        """Set filter and refresh."""
        self._filter = filter_text
        self.refresh()

    # ── Private ─────────────────────────────────────────────────

    def _api_filter(self):
        return FILTER_MAP.get(self._filter, "all")

    def _fetch_total_count(self):
        api = self._app.api
        if not api:
            return
        try:
            self._total_count = api.get_order_count(filter=self._api_filter())
            self.totalCountChanged.emit()
        except Exception:
            pass

    def _fetch_page(self, offset):
        api = self._app.api
        if not api:
            return []
        try:
            result = api.get_orders(
                filter=self._api_filter(),
                offset=offset,
                limit=PAGE_SIZE,
            )
            # Server returns {"orders": [...]} with pre-formatted items
            orders = result.get("orders", [])

            items = []
            for order in orders:
                # The server returns items already formatted for the model.
                # Map server response keys to model keys.
                production = order.get("production_status", "pending")
                fulfillment = order.get("fulfillment_status", "unfulfilled")

                items.append({
                    "orderNumber": order.get("order_number", ""),
                    "customerName": order.get("customer_name", ""),
                    "skus": order.get("skus", ""),
                    "total": order.get("total", ""),
                    "shopifyStatus": order.get("shopify_status", fulfillment.title() if fulfillment else "Unfulfilled"),
                    "productionStatus": order.get("production_status_display", production.replace("_", " ").title() if production else "Pending"),
                    "createdAt": order.get("created_at", ""),
                    "statusColor": STATUS_COLORS.get(production, ""),
                    "email": order.get("email", ""),
                    "phone": order.get("phone", ""),
                    "subtotalPrice": order.get("subtotal_price", ""),
                    "totalTax": order.get("total_tax", ""),
                    "totalDiscounts": order.get("total_discounts", ""),
                    "totalShipping": order.get("total_shipping", ""),
                    "financialStatus": order.get("financial_status", ""),
                    "note": order.get("note", ""),
                    "tags": order.get("tags", ""),
                    "sourceName": order.get("source_name", ""),
                    "shopifyOrderId": order.get("shopify_order_id", ""),
                    "displayName": order.get("display_name", ""),
                    "nestedAt": order.get("nested_at", ""),
                    "cutAt": order.get("cut_at", ""),
                    "packedAt": order.get("packed_at", ""),
                    "syncedAt": order.get("synced_at", ""),
                    "processedAt": order.get("processed_at", ""),
                    "cancelledAt": order.get("cancelled_at", ""),
                    "cancelReason": order.get("cancel_reason", ""),
                    "closedAt": order.get("closed_at", ""),
                    "shippingAddress": order.get("shipping_address", ""),
                    "billingAddress": order.get("billing_address", ""),
                    "discountCodes": order.get("discount_codes", ""),
                    "shippingMethod": order.get("shipping_method", ""),
                    "paymentMethod": order.get("payment_method", ""),
                    "landingSite": order.get("landing_site", ""),
                    "referringSite": order.get("referring_site", ""),
                })

            return items

        except Exception as e:
            self.statusMessage.emit(f"Error loading orders: {e}", 5000)
            return []

    def _update_can_load_more(self):
        can = self._offset < self._total_count
        if self._can_load_more != can:
            self._can_load_more = can
            self.canLoadMoreChanged.emit()
