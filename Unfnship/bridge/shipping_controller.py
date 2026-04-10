"""
Shipping queue controller — fetches unfulfilled orders, exposes to QML.
"""

import logging

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from bridge.models.orders_model import OrdersModel

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 10_000


class ShippingController(QObject):
    statusMessage = Signal(str, int)
    operationFailed = Signal(str)
    selectedOrderChanged = Signal()
    ratesChanged = Signal()
    ratesLoadingChanged = Signal()

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = OrdersModel(self)
        self._selected_order = {}
        self._rates = []
        self._rates_loading = False

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start()

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property("QVariantMap", notify=selectedOrderChanged)
    def selectedOrder(self):
        return self._selected_order

    @Property("QVariantList", notify=ratesChanged)
    def rates(self):
        return self._rates

    @Property(bool, notify=ratesLoadingChanged)
    def ratesLoading(self):
        return self._rates_loading

    @Slot()
    def refresh(self):
        api = self._app.api
        if not api:
            return
        try:
            queue = api.get_shipping_queue()
            self._model.resetItems(queue)
            self.statusMessage.emit(f"Loaded {len(queue)} orders", 3000)
        except Exception as e:
            logger.exception("Failed to refresh shipping queue")
            self.statusMessage.emit(f"Error loading orders: {e}", 5000)

    def _auto_refresh(self):
        if self._app.connectionOk:
            try:
                api = self._app.api
                if api:
                    queue = api.get_shipping_queue()
                    self._model.resetItems(queue)
            except Exception:
                pass

    @Slot(int)
    def selectOrder(self, row):
        """Set the selected order by row index. Clears any previous rates."""
        item = self._model.getItemAtRow(row)
        self._selected_order = item if item else {}
        self.selectedOrderChanged.emit()
        # Clear rates when switching orders
        if self._rates:
            self._rates = []
            self.ratesChanged.emit()

    @Slot()
    def clearSelection(self):
        self._selected_order = {}
        self.selectedOrderChanged.emit()
        if self._rates:
            self._rates = []
            self.ratesChanged.emit()

    @Slot(int, float, float, float, float)
    def getRates(self, order_id, weight_lbs, length_in, width_in, height_in):
        """Fetch shipping rates for an order from the server."""
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection")
            return
        self._rates_loading = True
        self.ratesLoadingChanged.emit()
        self._rates = []
        self.ratesChanged.emit()
        try:
            rates = api.get_rates(order_id, weight_lbs, length_in, width_in, height_in)
            self._rates = rates or []
            self.ratesChanged.emit()
            self.statusMessage.emit(f"Loaded {len(self._rates)} rates", 3000)
        except Exception as e:
            logger.exception("Failed to fetch rates")
            self.operationFailed.emit(f"Failed to fetch rates: {e}")
        finally:
            self._rates_loading = False
            self.ratesLoadingChanged.emit()
