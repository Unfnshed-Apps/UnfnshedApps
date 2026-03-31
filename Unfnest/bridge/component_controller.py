"""
Component CRUD controller + model exposure for QML.
"""

import logging
import shutil
from pathlib import Path

from PySide6.QtCore import Signal, Slot, QUrl, QThread

logger = logging.getLogger(__name__)

from bridge.models.component_model import ComponentListModel
from bridge.refreshable_controller import RefreshableController


class _ComponentRefreshWorker(QThread):
    """Background worker for fetching component data."""
    finished = Signal(list)

    def __init__(self, db, dxf_loader):
        super().__init__()
        self._db = db
        self._dxf_loader = dxf_loader

    def run(self):
        try:
            components = self._db.get_all_component_definitions()
            inv_map = {}
            if hasattr(self._db, "get_inventory_map"):
                try:
                    inv_map = self._db.get_inventory_map()
                except Exception:
                    logger.exception("Failed to fetch inventory map")
            items = []
            for comp in components:
                geom = self._dxf_loader.load_part(comp.dxf_filename) if self._dxf_loader else None
                items.append({
                    "id": comp.id,
                    "name": comp.name,
                    "dxf_filename": comp.dxf_filename,
                    "variable_pockets": comp.variable_pockets,
                    "has_geometry": geom is not None,
                    "inventory_count": inv_map.get(comp.id, 0),
                })
            self.finished.emit(items)
        except Exception:
            logger.exception("Failed to refresh components")
            self.finished.emit([])


class ComponentController(RefreshableController):
    operationFailed = Signal(str)

    def __init__(self, app_ctrl, parent=None):
        super().__init__(app_ctrl, ComponentListModel(), parent)

    def _create_refresh_worker(self):
        return _ComponentRefreshWorker(self._app.db, self._app.dxf_loader)

    @Slot(int, int)
    def setQuantity(self, row, value):
        idx = self._model.index(row, 0)
        self._model.setData(idx, value, ComponentListModel.QuantityRole)

    @Slot()
    def clearQuantities(self):
        self._model.clearQuantities()

    @Slot(int, result=int)
    def componentIdAtRow(self, row):
        item = self._model.getItemAtRow(row)
        return item["id"] if item else -1

    @Slot(str, str, bool, str, result=bool)
    def addComponent(self, name, dxf_filename, variable_pockets, mating_role="neutral"):
        db = self._app.db
        try:
            existing = db.get_component_definition_by_name(name)
            if existing:
                self.statusMessage.emit(f"A component named '{name}' already exists.", 5000)
                return False
            comp_id = db.add_component_definition(name, dxf_filename, variable_pockets)
            if mating_role != "neutral":
                db.update_component_definition(comp_id, name, dxf_filename, variable_pockets, mating_role=mating_role)
        except Exception:
            logger.exception("Failed to create component '%s'", name)
            self.operationFailed.emit(
                "Component failed to create. You are not connected to the database. "
                "Please retry once connection is established."
            )
            return False
        self.refresh()
        self.statusMessage.emit(f"Added component: {name}", 3000)
        return True

    @Slot(int, str, str, bool, str, result=bool)
    def updateComponent(self, component_id, name, dxf_filename, variable_pockets, mating_role="neutral"):
        db = self._app.db
        try:
            comp = db.get_component_definition(component_id)
            if not comp:
                return False
            if name != comp.name:
                existing = db.get_component_definition_by_name(name)
                if existing:
                    self.statusMessage.emit(f"A component named '{name}' already exists.", 5000)
                    return False
            db.update_component_definition(component_id, name, dxf_filename, variable_pockets, mating_role=mating_role)
        except Exception:
            logger.exception("Failed to update component %d '%s'", component_id, name)
            self.operationFailed.emit(
                "Component failed to update. You are not connected to the database. "
                "Please retry once connection is established."
            )
            return False
        self.refresh()
        self.statusMessage.emit(f"Updated component: {name}", 3000)
        return True

    @Slot(int, result=str)
    def deleteComponent(self, row):
        """Delete component at row. Returns empty string on success, or error message."""
        item = self._model.getItemAtRow(row)
        if not item:
            return "Component not found"
        db = self._app.db
        try:
            error = db.delete_component_definition(item["id"])
        except Exception:
            logger.exception("Failed to delete component %d", item["id"])
            return ("Component failed to delete. You are not connected to the database. "
                    "Please retry once connection is established.")
        if error:
            return error
        self.refresh()
        self.statusMessage.emit(f"Deleted component: {item['name']}", 3000)
        return ""

    @Slot(str, result=bool)
    def dxfHasPockets(self, dxf_filename):
        if not dxf_filename or not self._app.dxf_loader:
            return False
        try:
            part = self._app.dxf_loader.load_part(dxf_filename)
            return part is not None and bool(part.pocket_polygons)
        except Exception:
            logger.exception("Failed to check pockets for '%s'", dxf_filename)
            return False

    @Slot(int, result="QVariantMap")
    def getComponentData(self, component_id):
        """Get component data for editing."""
        db = self._app.db
        comp = db.get_component_definition(component_id)
        if not comp:
            return {}
        return {
            "id": comp.id,
            "name": comp.name,
            "dxf_filename": comp.dxf_filename,
            "variable_pockets": comp.variable_pockets,
            "mating_role": getattr(comp, "mating_role", "neutral"),
        }

    @Slot(str, result=str)
    def importDxfFile(self, file_url):
        """Import a DXF file. file_url is a file:// URL from FileDialog."""
        source = Path(QUrl(file_url).toLocalFile())
        if not source.exists():
            return ""
        dxf_loader = self._app.dxf_loader
        dest = dxf_loader.dxf_directory / source.name
        try:
            shutil.copy2(source, dest)
        except Exception:
            logger.exception("Failed to import DXF file '%s'", source.name)
            self.statusMessage.emit(f"Failed to import {source.name}", 5000)
            return ""
        # Upload to server if available
        if self._app.api_client:
            try:
                self._app.api_client.upload_component_dxf(source)
            except Exception:
                logger.exception("Failed to upload DXF '%s' to server", source.name)
                self.statusMessage.emit(
                    f"File saved locally but failed to upload to server", 5000
                )
        return source.name

