"""
Product CRUD controller + model for QML.
"""

import logging

from PySide6.QtCore import Signal, Slot, QThread

logger = logging.getLogger(__name__)

from bridge.models.product_model import ProductListModel
from bridge.refreshable_controller import RefreshableController


class _ProductRefreshWorker(QThread):
    """Background worker for fetching product data."""
    finished = Signal(list)

    def __init__(self, db):
        super().__init__()
        self._db = db

    def run(self):
        try:
            products = self._db.get_all_products()
            items = []
            for p in products:
                items.append({
                    "sku": p.sku,
                    "name": p.name,
                    "outsourced": p.outsourced,
                })
            self.finished.emit(items)
        except Exception:
            logger.exception("Failed to refresh products")
            self.finished.emit([])


class ProductController(RefreshableController):
    operationFailed = Signal(str)

    def __init__(self, app_ctrl, parent=None):
        super().__init__(app_ctrl, ProductListModel(), parent)

    def _create_refresh_worker(self):
        return _ProductRefreshWorker(self._app.db)

    @Slot(int, int)
    def setQuantity(self, row, value):
        idx = self._model.index(row, 0)
        self._model.setData(idx, value, ProductListModel.QuantityRole)

    @Slot()
    def clearQuantities(self):
        self._model.clearQuantities()

    @Slot(int, result=str)
    def skuAtRow(self, row):
        item = self._model.getItemAtRow(row)
        return item["sku"] if item else ""

    @Slot(str, str, str, bool, "QVariantList", "QVariantList", result=bool)
    def addProduct(self, sku, name, description, outsourced, components, mating_pairs):
        """Add product. components: [[component_id, qty], ...], mating_pairs: [[pocket_id, mating_id, pocket_index, clearance], ...]."""
        db = self._app.db
        try:
            if db.get_product(sku):
                self.statusMessage.emit(f"A product with SKU '{sku}' already exists.", 5000)
                return False
            db.add_product(sku, name, description, outsourced)
            for pair in components:
                db.add_product_component(sku, int(pair[0]), int(pair[1]))
            self._save_mating_pairs(db, sku, mating_pairs)
        except Exception:
            logger.exception("Failed to create product '%s'", sku)
            self.operationFailed.emit(
                "Product failed to create. You are not connected to the database. "
                "Please retry once connection is established."
            )
            return False
        self.refresh()
        self.statusMessage.emit(f"Added product: {sku}", 3000)
        return True

    @Slot(str, str, str, bool, "QVariantList", "QVariantList", result=bool)
    def updateProduct(self, sku, name, description, outsourced, components, mating_pairs):
        db = self._app.db
        try:
            db.add_product(sku, name, description, outsourced)
            db.clear_product_components(sku)
            for pair in components:
                db.add_product_component(sku, int(pair[0]), int(pair[1]))
            self._save_mating_pairs(db, sku, mating_pairs)
        except Exception:
            logger.exception("Failed to update product '%s'", sku)
            self.operationFailed.emit(
                "Product failed to update. You are not connected to the database. "
                "Please retry once connection is established."
            )
            return False
        self.refresh()
        self.statusMessage.emit(f"Updated product: {sku}", 3000)
        return True

    def _save_mating_pairs(self, db, sku, mating_pairs):
        """Save mating pairs via PUT with components + mating_pairs."""
        if not hasattr(db, '_put'):
            return  # Local SQLite — no mating pairs support
        product = db.get_product(sku)
        if not product:
            return
        mp_list = []
        for mp in mating_pairs:
            mp_list.append({
                "pocket_component_id": int(mp[0]),
                "mating_component_id": int(mp[1]),
                "pocket_index": int(mp[2]) if len(mp) > 2 else 0,
                "clearance_inches": float(mp[3]) if len(mp) > 3 else 0.0079,
            })
        db._put(f"/products/{sku}", {"mating_pairs": mp_list})

    @Slot(int, result=bool)
    def deleteProduct(self, row):
        item = self._model.getItemAtRow(row)
        if not item:
            return False
        db = self._app.db
        try:
            db.delete_product(item["sku"])
        except Exception:
            logger.exception("Failed to delete product '%s'", item["sku"])
            self.operationFailed.emit(
                "Product failed to delete. You are not connected to the database. "
                "Please retry once connection is established."
            )
            return False
        self.refresh()
        self.statusMessage.emit(f"Deleted product: {item['sku']}", 3000)
        return True

    @Slot(str, result="QVariantMap")
    def getProduct(self, sku):
        """Get product details for editing."""
        db = self._app.db
        p = db.get_product(sku)
        if not p:
            return {}
        # Build component list with mating roles from definitions
        all_defs = {d.id: d for d in db.get_all_component_definitions()}
        comps = []
        for c in p.components:
            comp_def = all_defs.get(c.component_id)
            comps.append({
                "component_id": c.component_id,
                "component_name": c.component_name,
                "dxf_filename": c.dxf_filename,
                "quantity": c.quantity,
                "mating_role": getattr(comp_def, "mating_role", "neutral") if comp_def else "neutral",
            })
        pairs = []
        for mp in p.mating_pairs:
            pairs.append({
                "pocket_component_id": mp.pocket_component_id,
                "mating_component_id": mp.mating_component_id,
                "pocket_index": mp.pocket_index,
                "clearance_inches": mp.clearance_inches,
            })
        return {
            "sku": p.sku,
            "name": p.name,
            "description": p.description,
            "outsourced": p.outsourced,
            "components": comps,
            "mating_pairs": pairs,
        }

    @Slot(result="QVariantList")
    def getAllComponentDefinitions(self):
        """Get all component definitions for combo box in product dialog."""
        db = self._app.db
        comps = db.get_all_component_definitions()
        result = []
        for c in comps:
            result.append({
                "id": c.id,
                "name": c.name,
                "dxf_filename": c.dxf_filename,
                "mating_role": getattr(c, "mating_role", "neutral"),
            })
        return result
