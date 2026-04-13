"""
Shipping queue controller — fetches unfulfilled orders, exposes to QML.
Supports multi-parcel orders: each parcel has its own dimensions,
rates, and purchased label.
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
    testModeChanged = Signal()
    activeKeyPresentChanged = Signal()
    parcelsChanged = Signal()
    ratesLoadingChanged = Signal()
    fulfillBusyChanged = Signal()

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = OrdersModel(self)
        self._selected_order = {}

        self._test_mode = True
        self._active_key_present = False
        self._rates_loading = False
        self._fulfill_busy = False

        # Multi-parcel state — parallel lists indexed by parcel number.
        # _parcels[i] = {weight, length, width, height}
        # _parcel_rates[i] = [rate1, rate2, ...] or []
        # _purchased_labels[i] = {label dict} or {}
        self._parcels = []
        self._parcel_rates = []
        self._purchased_labels = []

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start()

    # ==================== Properties ====================

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property("QVariantMap", notify=selectedOrderChanged)
    def selectedOrder(self):
        return self._selected_order

    @Property(bool, notify=testModeChanged)
    def testMode(self):
        return self._test_mode

    @Property(bool, notify=activeKeyPresentChanged)
    def activeKeyPresent(self):
        return self._active_key_present

    @Property(bool, notify=ratesLoadingChanged)
    def ratesLoading(self):
        return self._rates_loading

    @Property(bool, notify=fulfillBusyChanged)
    def fulfillBusy(self):
        return self._fulfill_busy

    @Property("QVariantList", notify=parcelsChanged)
    def parcels(self):
        """List of parcel state dicts for QML.

        Each dict: {index, weight, length, width, height,
                    rates: [...], label: {...} or {}, rates_loading: bool}
        """
        result = []
        for i, p in enumerate(self._parcels):
            rates = self._parcel_rates[i] if i < len(self._parcel_rates) else []
            label = self._purchased_labels[i] if i < len(self._purchased_labels) else {}
            result.append({
                "index": i,
                "weight": p["weight"],
                "length": p["length"],
                "width": p["width"],
                "height": p["height"],
                "rates": rates,
                "label": label,
            })
        return result

    @Property(int, notify=parcelsChanged)
    def parcelCount(self):
        return len(self._parcels)

    @Property(bool, notify=parcelsChanged)
    def allLabelsReady(self):
        """True when every parcel has a purchased label."""
        if not self._parcels:
            return False
        return all(
            bool(lbl.get("tracking_number"))
            for lbl in self._purchased_labels
        )

    # ==================== Queue ====================

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

    # ==================== Order Selection ====================

    @Slot(int)
    def selectOrder(self, row):
        item = self._model.getItemAtRow(row)
        self._selected_order = item if item else {}
        self.selectedOrderChanged.emit()
        self._clear_parcel_state()

    @Slot()
    def clearSelection(self):
        self._selected_order = {}
        self.selectedOrderChanged.emit()
        self._clear_parcel_state()

    def _clear_parcel_state(self):
        if self._parcels or self._parcel_rates or self._purchased_labels:
            self._parcels = []
            self._parcel_rates = []
            self._purchased_labels = []
            self.parcelsChanged.emit()

    # ==================== Multi-Parcel Flow ====================

    @Slot(int, float, float, float, float)
    def addParcel(self, order_id, weight_lbs, length_in, width_in, height_in):
        """Add a parcel and immediately fetch rates for it."""
        parcel = {
            "weight": weight_lbs,
            "length": length_in,
            "width": width_in,
            "height": height_in,
        }
        self._parcels.append(parcel)
        self._parcel_rates.append([])
        self._purchased_labels.append({})
        parcel_index = len(self._parcels) - 1
        self.parcelsChanged.emit()

        # Fetch rates for this parcel
        self._fetch_rates_for_parcel(order_id, parcel_index)

    @Slot(int)
    def removeParcel(self, parcel_index):
        """Remove a parcel that doesn't have a purchased label."""
        if parcel_index < 0 or parcel_index >= len(self._parcels):
            return
        label = self._purchased_labels[parcel_index]
        if label.get("tracking_number"):
            self.operationFailed.emit("Cannot remove a parcel with a purchased label")
            return
        del self._parcels[parcel_index]
        del self._parcel_rates[parcel_index]
        del self._purchased_labels[parcel_index]
        self.parcelsChanged.emit()

    def _fetch_rates_for_parcel(self, order_id, parcel_index):
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection")
            return

        self._rates_loading = True
        self.ratesLoadingChanged.emit()

        parcel = self._parcels[parcel_index]
        try:
            response = api.get_rates(
                order_id,
                parcel["weight"],
                parcel["length"],
                parcel["width"],
                parcel["height"],
            )
            self._check_response_test_mode(response)
            rates = response.get("rates", []) if isinstance(response, dict) else []
            self._parcel_rates[parcel_index] = rates or []
            self.parcelsChanged.emit()
            self.statusMessage.emit(
                f"Parcel {parcel_index + 1}: {len(rates)} rates loaded", 3000
            )
        except Exception as e:
            logger.exception("Failed to fetch rates for parcel %d", parcel_index)
            self.operationFailed.emit(f"Failed to fetch rates: {e}")
        finally:
            self._rates_loading = False
            self.ratesLoadingChanged.emit()

    @Slot(str, int, int)
    def purchaseLabel(self, rate_id, order_id, parcel_index):
        """Purchase a label for a specific parcel."""
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection")
            return

        if parcel_index < 0 or parcel_index >= len(self._parcels):
            self.operationFailed.emit("Invalid parcel index")
            return

        try:
            response = api.purchase_label(rate_id, order_id)
        except Exception as e:
            logger.exception("Failed to purchase label for parcel %d", parcel_index)
            self.operationFailed.emit(f"Failed to purchase label: {e}")
            return

        self._purchased_labels[parcel_index] = response
        self.parcelsChanged.emit()

        label_url = response.get("label_url", "")
        tracking = response.get("tracking_number", "")
        carrier = response.get("carrier", "")

        if label_url:
            self._print_label(label_url)

        self.statusMessage.emit(
            f"Parcel {parcel_index + 1} label — {carrier} tracking: {tracking}", 8000
        )

    @Slot(int)
    def reprintLabel(self, parcel_index):
        """Reprint a specific parcel's label."""
        if parcel_index < 0 or parcel_index >= len(self._purchased_labels):
            self.operationFailed.emit("No label to reprint")
            return
        label_url = self._purchased_labels[parcel_index].get("label_url", "")
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

    # ==================== Fulfillment ====================

    @Slot(int)
    def fulfillOrder(self, order_id):
        """Mark an order as fulfilled — deducts inventory, sends all
        tracking numbers to Shopify."""
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection")
            return

        # Build tracking entries from all purchased labels
        tracking_entries = []
        for lbl in self._purchased_labels:
            tn = lbl.get("tracking_number", "")
            if tn:
                tracking_entries.append({
                    "tracking_number": tn,
                    "carrier": lbl.get("carrier", ""),
                })

        if not tracking_entries:
            self.operationFailed.emit("No labels purchased — cannot fulfill")
            return

        self._fulfill_busy = True
        self.fulfillBusyChanged.emit()

        try:
            response = api.fulfill_order(order_id, tracking_entries=tracking_entries)
        except Exception as e:
            logger.exception("Failed to fulfill order")
            self.operationFailed.emit(f"Failed to fulfill order: {e}")
            return
        finally:
            self._fulfill_busy = False
            self.fulfillBusyChanged.emit()

        shopify_pushed = response.get("shopify_pushed", False)
        n = len(tracking_entries)
        msg = f"Order fulfilled — {n} parcel{'s' if n > 1 else ''}, inventory deducted"
        if shopify_pushed:
            msg += ", tracking pushed to Shopify"
        self.statusMessage.emit(msg, 8000)

        # Clear and refresh
        self._clear_parcel_state()
        self._selected_order = {}
        self.selectedOrderChanged.emit()
        self.refresh()
