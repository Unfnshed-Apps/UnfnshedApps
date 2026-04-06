"""
Product inventory controller — refresh, adjust, model exposure for QML.
"""

import logging
from datetime import datetime

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from bridge.models.product_inventory_model import ProductInventoryModel

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 10_000  # 10 seconds


class ProductInventoryController(QObject):
    statusMessage = Signal(str, int)  # message, timeout_ms
    operationFailed = Signal(str)  # error message for popup dialog

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = ProductInventoryModel(self)

        # Auto-refresh timer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.refresh)
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
            inventory = api.get_product_inventory()

            # Fetch product replenishment status for targets/velocity data
            repl_map = {}
            try:
                repl_status = api.get_product_replenishment_status()
                for rs in repl_status:
                    repl_map[rs.get("product_sku")] = rs
            except Exception as e:
                logger.warning("Failed to fetch product replenishment status: %s", e)

            items = []
            for prod in inventory:
                last_updated = ""
                lu = prod.get("last_updated")
                if lu:
                    try:
                        dt = datetime.fromisoformat(lu.replace("Z", "+00:00"))
                        last_updated = dt.strftime("%m/%d %H:%M")
                    except (ValueError, TypeError):
                        pass

                sku = prod.get("product_sku", "")
                repl = repl_map.get(sku, {})

                items.append({
                    "sku": sku,
                    "name": prod.get("product_name", ""),
                    "stock": prod.get("quantity_on_hand", 0),
                    "last_updated": last_updated,
                    "target_stock": repl.get("target_stock", 0),
                    "velocity": repl.get("velocity", 0.0),
                    "status": repl.get("status", "adequate"),
                })
            self._model.resetItems(items)
            self.statusMessage.emit(f"Loaded {len(items)} products", 3000)
        except Exception as e:
            self.statusMessage.emit(f"Error loading product inventory: {e}", 5000)

    @Slot(str, int, str, str, result=bool)
    def adjustInventory(self, sku, quantity, reason, notes):
        api = self._app.api
        if not api:
            self.operationFailed.emit(
                "Not connected to the database. "
                "Please retry once connection is established."
            )
            return False
        try:
            api.adjust_product_inventory(
                sku, quantity, reason, notes or None
            )
            self.refresh()
            return True
        except Exception as e:
            self.operationFailed.emit(f"Failed to adjust inventory: {e}")
            return False

