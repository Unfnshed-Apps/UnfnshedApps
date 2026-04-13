"""
Shipping queue controller — fetches unfulfilled orders, exposes to QML.
"""

import logging
import subprocess
import tempfile
import urllib.request

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from bridge.models.orders_model import OrdersModel
from src.config import load_config

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 10_000


class ShippingController(QObject):
    statusMessage = Signal(str, int)
    operationFailed = Signal(str)
    selectedOrderChanged = Signal()
    ratesChanged = Signal()
    ratesLoadingChanged = Signal()
    testModeChanged = Signal()
    activeKeyPresentChanged = Signal()
    purchasedLabelChanged = Signal()
    fulfillBusyChanged = Signal()

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = OrdersModel(self)
        self._selected_order = {}
        self._rates = []
        self._rates_loading = False
        # Test mode state — populated from /shipping/status on connect and
        # refreshed whenever a /shipping/* response advertises a different
        # mode than what we last saw. Defaults to True (safest) until the
        # server tells us otherwise.
        self._test_mode = True
        self._active_key_present = False

        # Last purchased label — holds {label_url, tracking_number, carrier,
        # service, transaction_id, test_mode} after a successful purchase.
        self._purchased_label = {}

        # Busy flag for fulfill operation
        self._fulfill_busy = False

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

    @Property(bool, notify=testModeChanged)
    def testMode(self):
        """True when the server is using a Shippo test key.

        Drives the TEST MODE banner in Main.qml. Refreshed on connect and
        whenever a shipping API response advertises a different value than
        what we last saw (multi-tab coherence).
        """
        return self._test_mode

    @Property(bool, notify=activeKeyPresentChanged)
    def activeKeyPresent(self):
        """True when the active Shippo key (test or live, per the toggle)
        is configured. When False, mutation buttons disable themselves to
        prevent failed requests.
        """
        return self._active_key_present

    @Property("QVariantMap", notify=purchasedLabelChanged)
    def purchasedLabel(self):
        return self._purchased_label

    @Property(bool, notify=fulfillBusyChanged)
    def fulfillBusy(self):
        return self._fulfill_busy

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

    @Slot()
    def refreshStatus(self):
        """Fetch /shipping/status and update test mode + active key state.

        Called from app_controller._on_connected() and after any shipping
        response that advertised a test_mode value different from our local
        state (multi-tab coherence).
        """
        api = self._app.api
        if not api:
            return
        try:
            status = api.get_shipping_status()
        except Exception:
            logger.exception("Failed to refresh shipping status")
            return
        new_test_mode = bool(status.get("test_mode", True))
        new_active = bool(status.get("active_key_present", False))
        if new_test_mode != self._test_mode:
            self._test_mode = new_test_mode
            self.testModeChanged.emit()
        if new_active != self._active_key_present:
            self._active_key_present = new_active
            self.activeKeyPresentChanged.emit()

    def _check_response_test_mode(self, response):
        """Detect drift between server-reported test_mode and our local state.

        Every shipping API response includes ``test_mode``. If it doesn't
        match what we last saw, the toggle changed in another tab/window —
        re-fetch the full status and warn the user via a status message.
        """
        if not isinstance(response, dict):
            return
        server_mode = response.get("test_mode")
        if server_mode is None:
            return
        if bool(server_mode) != self._test_mode:
            self.refreshStatus()
            self.statusMessage.emit("Test mode changed — refreshed status", 5000)

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
        # Clear rates and purchased label when switching orders
        if self._rates:
            self._rates = []
            self.ratesChanged.emit()
        if self._purchased_label:
            self._purchased_label = {}
            self.purchasedLabelChanged.emit()

    @Slot()
    def clearSelection(self):
        self._selected_order = {}
        self.selectedOrderChanged.emit()
        if self._rates:
            self._rates = []
            self.ratesChanged.emit()
        if self._purchased_label:
            self._purchased_label = {}
            self.purchasedLabelChanged.emit()

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
            response = api.get_rates(order_id, weight_lbs, length_in, width_in, height_in)
            # Server returns {rates: [...], test_mode: bool}.
            self._check_response_test_mode(response)
            rates = response.get("rates", []) if isinstance(response, dict) else []
            self._rates = rates or []
            self.ratesChanged.emit()
            self.statusMessage.emit(f"Loaded {len(self._rates)} rates", 3000)
        except Exception as e:
            logger.exception("Failed to fetch rates")
            self.operationFailed.emit(f"Failed to fetch rates: {e}")
        finally:
            self._rates_loading = False
            self.ratesLoadingChanged.emit()

    @Slot(str, int)
    def purchaseLabel(self, rate_id, order_id):
        """Purchase a shipping label and send it to the configured printer."""
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection")
            return

        try:
            response = api.purchase_label(rate_id, order_id)
        except Exception as e:
            logger.exception("Failed to purchase label")
            self.operationFailed.emit(f"Failed to purchase label: {e}")
            return

        self._purchased_label = response
        self.purchasedLabelChanged.emit()

        label_url = response.get("label_url", "")
        tracking = response.get("tracking_number", "")
        carrier = response.get("carrier", "")

        if label_url:
            self._print_label(label_url)

        self.statusMessage.emit(
            f"Label purchased — {carrier} tracking: {tracking}", 8000
        )

    @Slot()
    def reprintLabel(self):
        """Reprint the last purchased label."""
        label_url = self._purchased_label.get("label_url", "")
        if not label_url:
            self.operationFailed.emit("No label to reprint")
            return
        self._print_label(label_url)

    def _print_label(self, label_url):
        """Download a label PDF and send it to the configured printer."""
        config = load_config()
        printer_name = config.label_printer
        if not printer_name:
            self.statusMessage.emit(
                "No label printer configured — set one in Shipping Settings", 5000
            )
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                req = urllib.request.Request(label_url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    tmp.write(resp.read())
                tmp_path = tmp.name

            subprocess.run(
                ["lpr", "-P", printer_name, tmp_path],
                check=True,
                capture_output=True,
            )
            self.statusMessage.emit(f"Label sent to {printer_name}", 5000)
        except Exception as e:
            logger.exception("Failed to print label")
            self.operationFailed.emit(f"Failed to print label: {e}")

    @Slot(int, str, str)
    def fulfillOrder(self, order_id, tracking_number, carrier):
        """Mark an order as fulfilled — deducts inventory, optionally pushes
        tracking to Shopify."""
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection")
            return

        self._fulfill_busy = True
        self.fulfillBusyChanged.emit()

        try:
            response = api.fulfill_order(order_id, tracking_number, carrier)
        except Exception as e:
            logger.exception("Failed to fulfill order")
            self.operationFailed.emit(f"Failed to fulfill order: {e}")
            return
        finally:
            self._fulfill_busy = False
            self.fulfillBusyChanged.emit()

        shopify_pushed = response.get("shopify_pushed", False)
        msg = "Order fulfilled — inventory deducted"
        if shopify_pushed:
            msg += ", tracking pushed to Shopify"
        self.statusMessage.emit(msg, 8000)

        # Clear selection and refresh the queue
        self._purchased_label = {}
        self.purchasedLabelChanged.emit()
        self._selected_order = {}
        self.selectedOrderChanged.emit()
        self._rates = []
        self.ratesChanged.emit()
        self.refresh()
