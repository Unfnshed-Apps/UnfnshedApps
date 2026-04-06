"""
Inventory data controller — refresh, adjust, model exposure for QML.
"""

import json

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from bridge.models.inventory_model import InventoryListModel

REFRESH_INTERVAL_MS = 10_000  # 10 seconds


class InventoryController(QObject):
    statusMessage = Signal(str, int)  # message, timeout_ms
    operationFailed = Signal(str)  # error message for popup dialog
    replenishmentConfigLoaded = Signal("QVariant")  # config dict

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = InventoryListModel(self)

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
            inventory = api.get_component_inventory()

            # Fetch replenishment status for target/reorder/ABC data
            repl_map = {}
            try:
                repl_status = api.get_replenishment_status()
                for rs in repl_status:
                    repl_map[rs.get("component_id")] = rs
            except Exception:
                pass  # Server may not have replenishment tables yet

            items = []
            for comp in inventory:
                last_updated = ""
                if comp.last_updated:
                    last_updated = comp.last_updated.strftime("%m/%d %H:%M")

                repl = repl_map.get(comp.id, {})
                items.append({
                    "id": comp.id,
                    "name": comp.component_name,
                    "dxf_filename": comp.dxf_filename,
                    "stock": comp.stock,
                    "last_updated": last_updated,
                    "target_stock": repl.get("target_stock", 0),
                    "velocity": repl.get("velocity", 0.0),
                    "pipeline": repl.get("pipeline", 0),
                })
            self._model.resetItems(items)
            self.statusMessage.emit(f"Loaded {len(items)} components", 3000)
        except Exception as e:
            self.statusMessage.emit(f"Error loading inventory: {e}", 5000)

    @Slot(int, int, str, str, result=bool)
    def adjustInventory(self, componentId, quantity, reason, notes):
        api = self._app.api
        if not api:
            self.operationFailed.emit(
                "Not connected to the database. "
                "Please retry once connection is established."
            )
            return False
        try:
            api.adjust_component_inventory(
                componentId, quantity, reason, notes or None
            )
            self.refresh()
            return True
        except Exception as e:
            self.operationFailed.emit(f"Failed to adjust inventory: {e}")
            return False

    @Slot()
    def recalculateForecasts(self):
        """Trigger full replenishment recalculation on the server."""
        api = self._app.api
        if not api:
            self.operationFailed.emit(
                "Not connected to the database. "
                "Please retry once connection is established."
            )
            return
        try:
            self.statusMessage.emit("Recalculating forecasts...", 0)
            result = api.recalculate_replenishment()
            msg = result.get("message", "Recalculation complete")
            self.statusMessage.emit(msg, 5000)
            self.refresh()
        except Exception as e:
            self.statusMessage.emit(f"Recalculation failed: {e}", 5000)

    @Slot()
    def loadReplenishmentConfig(self):
        """Fetch replenishment config from the server."""
        api = self._app.api
        if not api:
            return
        try:
            cfg = api.get_replenishment_config()
            self.replenishmentConfigLoaded.emit(cfg)
        except Exception as e:
            self.statusMessage.emit(f"Failed to load config: {e}", 5000)

    @Slot(str)
    def saveReplenishmentConfig(self, updates_json):
        """Save replenishment config updates to the server and recalculate."""
        api = self._app.api
        if not api:
            self.operationFailed.emit(
                "Not connected to the database. "
                "Please retry once connection is established."
            )
            return
        try:
            updates = json.loads(updates_json)
            api.update_replenishment_config(updates)
            self.statusMessage.emit("Settings saved. Recalculating...", 0)
            api.recalculate_replenishment()
            self.statusMessage.emit("Settings saved and forecasts recalculated.", 5000)
            self.refresh()
        except Exception as e:
            self.operationFailed.emit(f"Failed to save settings: {e}")
