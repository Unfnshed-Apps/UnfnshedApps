"""
Replenishment controller — fetches product stock status from server,
triggers replenishment nesting via the standard product nesting path,
exposes model to QML.
"""

import logging

from PySide6.QtCore import (
    Qt, QObject, Property, Signal, Slot, QThread, QTimer,
    QAbstractListModel, QModelIndex, QByteArray,
)

logger = logging.getLogger(__name__)


class ReplenishmentModel(QAbstractListModel):
    """List model exposing product replenishment status to QML."""

    SkuRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    StockRole = Qt.UserRole + 3
    TargetStockRole = Qt.UserRole + 4
    ReorderPointRole = Qt.UserRole + 5
    AbcClassRole = Qt.UserRole + 6
    VelocityRole = Qt.UserRole + 7
    StatusRole = Qt.UserRole + 8
    DeficitRole = Qt.UserRole + 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def roleNames(self):
        return {
            self.SkuRole: QByteArray(b"sku"),
            self.NameRole: QByteArray(b"name"),
            self.StockRole: QByteArray(b"stock"),
            self.TargetStockRole: QByteArray(b"targetStock"),
            self.ReorderPointRole: QByteArray(b"reorderPoint"),
            self.AbcClassRole: QByteArray(b"abcClass"),
            self.VelocityRole: QByteArray(b"velocity"),
            self.StatusRole: QByteArray(b"stockStatus"),
            self.DeficitRole: QByteArray(b"deficit"),
        }

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        role_map = {
            self.SkuRole: "product_sku",
            self.NameRole: "product_name",
            self.StockRole: "current_stock",
            self.TargetStockRole: "target_stock",
            self.ReorderPointRole: "reorder_point",
            self.AbcClassRole: "abc_class",
            self.VelocityRole: "velocity",
            self.StatusRole: "status",
            self.DeficitRole: "deficit",
        }
        key = role_map.get(role)
        if key:
            return item.get(key)
        return None

    def resetItems(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def getDeficits(self):
        """Return {sku: deficit} for all products with deficit > 0."""
        result = {}
        for item in self._items:
            deficit = item.get("deficit", 0)
            if deficit > 0:
                result[item["product_sku"]] = deficit
        return result


class _StatusRefreshWorker(QThread):
    """Background thread for fetching product replenishment status."""
    finished = Signal(list)

    def __init__(self, api):
        super().__init__()
        self._api = api

    def run(self):
        try:
            data = self._api.get_product_replenishment_status()
            self.finished.emit(data)
        except Exception:
            logger.exception("Failed to fetch replenishment status")
            self.finished.emit([])


class RecalculateWorker(QThread):
    """Background thread for recalculate operation."""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, api):
        super().__init__()
        self._api = api

    def run(self):
        try:
            result = self._api.recalculate_replenishment()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ReplenishmentController(QObject):
    modelChanged = Signal()
    statusMessage = Signal(str, int)
    isLoadingChanged = Signal()

    REFRESH_INTERVAL_MS = 10_000

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = ReplenishmentModel(self)
        self._is_loading = False
        self._worker = None
        self._nesting_ctrl = None
        self._refresh_worker = None

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start(self.REFRESH_INTERVAL_MS)

    def set_nesting_controller(self, ctrl):
        self._nesting_ctrl = ctrl

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property(bool, notify=isLoadingChanged)
    def isLoading(self):
        return self._is_loading

    def _auto_refresh(self):
        """Silent periodic refresh — runs off the main thread."""
        if not self._app.usingApi or self._is_loading:
            return
        if self._refresh_worker and self._refresh_worker.isRunning():
            return
        self._refresh_worker = _StatusRefreshWorker(self._app.db)
        self._refresh_worker.finished.connect(self._on_auto_refresh_done)
        self._refresh_worker.start()

    def _on_auto_refresh_done(self, data):
        self._model.resetItems(data)

    @Slot()
    def refresh(self):
        """Fetch product replenishment status from server (user-triggered)."""
        if not self._app.usingApi:
            return
        if self._refresh_worker and self._refresh_worker.isRunning():
            return
        self._set_loading(True)
        self._refresh_worker = _StatusRefreshWorker(self._app.db)
        self._refresh_worker.finished.connect(self._on_refresh_done)
        self._refresh_worker.start()

    def _on_refresh_done(self, data):
        self._model.resetItems(data)
        self.statusMessage.emit(f"Loaded {len(data)} product statuses", 3000)
        self._set_loading(False)

    @Slot()
    def recalculate(self):
        """Run full forecast update + replenishment calculation on server."""
        if not self._app.usingApi:
            self.statusMessage.emit("Not connected to server", 5000)
            return

        self._set_loading(True)
        self.statusMessage.emit("Recalculating forecasts and replenishment needs...", 0)

        self._worker = RecalculateWorker(self._app.db)
        self._worker.finished.connect(self._on_recalculate_done)
        self._worker.error.connect(self._on_recalculate_error)
        self._worker.start()

    def _on_recalculate_done(self, result):
        self._set_loading(False)
        self.statusMessage.emit("Recalculation complete", 5000)
        self.refresh()

    def _on_recalculate_error(self, error_msg):
        self._set_loading(False)
        self.statusMessage.emit(f"Recalculation failed: {error_msg}", 5000)

    @Slot()
    def runReplenishmentNesting(self):
        """Collect product deficits and nest via the standard product path."""
        if not self._nesting_ctrl:
            self.statusMessage.emit("Nesting controller not available", 5000)
            return
        if not self._app.usingApi:
            self.statusMessage.emit("Not connected to server", 5000)
            return
        if self._nesting_ctrl.isRunning:
            self.statusMessage.emit("Nesting already in progress", 5000)
            return

        deficits = self._model.getDeficits()  # {sku: deficit}
        if not deficits:
            self.statusMessage.emit("No replenishment needs — stock is adequate", 5000)
            return

        skus = len(deficits)
        self.statusMessage.emit(
            f"Replenishment nesting: {skus} products...", 0
        )
        if not self._nesting_ctrl.nestProducts(deficits):
            self.statusMessage.emit("No parts to nest (missing DXF files?)", 5000)

    def _set_loading(self, loading):
        self._is_loading = loading
        self.isLoadingChanged.emit()
