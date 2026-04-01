"""
Machine registry controller for QML.
"""

import logging

from PySide6.QtCore import QObject, Signal, Slot, QThread

logger = logging.getLogger(__name__)

from bridge.models.machine_model import MachineListModel


class _MachineRefreshWorker(QThread):
    """Background worker for fetching machine data."""
    finished = Signal(list)

    def __init__(self, db):
        super().__init__()
        self._db = db

    def run(self):
        try:
            if hasattr(self._db, 'list_machines'):
                machines = self._db.list_machines()
                self.finished.emit(machines)
            else:
                self.finished.emit([])
        except Exception:
            logger.exception("Failed to refresh machines")
            self.finished.emit([])


class MachineController(QObject):
    statusMessage = Signal(str, int)
    operationFailed = Signal(str)
    modelChanged = Signal()

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = MachineListModel()
        self._worker = None

    @Slot()
    def refresh(self):
        if self._worker and self._worker.isRunning():
            return
        self._worker = _MachineRefreshWorker(self._app.db)
        self._worker.finished.connect(self._on_refresh)
        self._worker.start()

    def _on_refresh(self, items):
        self._model.resetItems(items)
        self.modelChanged.emit()

    @Slot(result=QObject)
    def getModel(self):
        return self._model

    model = property(lambda self: self._model)

    @Slot(str, result=bool)
    def registerMachine(self, name):
        """Register a new machine."""
        name = name.strip()
        if not name:
            return False
        db = self._app.db
        try:
            db.create_machine(name)
        except Exception:
            logger.exception("Failed to register machine '%s'", name)
            self.operationFailed.emit("Failed to register machine. Check connection.")
            return False
        self.refresh()
        self.statusMessage.emit(f"Registered machine: {name}", 3000)
        return True

    @Slot(int, bool)
    def setActive(self, row, active):
        """Toggle a machine's active status."""
        item = self._model.getItemAtRow(row)
        if not item:
            return
        db = self._app.db
        try:
            db.update_machine(item["id"], active=active)
        except Exception:
            logger.exception("Failed to update machine %d", item["id"])
            self.operationFailed.emit("Failed to update machine. Check connection.")
            return
        self.refresh()

    @Slot(int, result=bool)
    def deleteMachine(self, row):
        """Delete a machine."""
        item = self._model.getItemAtRow(row)
        if not item:
            return False
        db = self._app.db
        try:
            db.delete_machine(item["id"])
        except Exception:
            logger.exception("Failed to delete machine %d", item["id"])
            self.operationFailed.emit("Failed to delete machine. Check connection.")
            return False
        self.refresh()
        self.statusMessage.emit(f"Deleted machine: {item['name']}", 3000)
        return True
