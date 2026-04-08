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

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = OrdersModel(self)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start()

    @Property(QObject, constant=True)
    def model(self):
        return self._model

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

    @Slot(int, result="QVariantMap")
    def getOrderDetail(self, row):
        """Get full order data for the detail view."""
        item = self._model.getItemAtRow(row)
        if not item:
            return {}
        return item
