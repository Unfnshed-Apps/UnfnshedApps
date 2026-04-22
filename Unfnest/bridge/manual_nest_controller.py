"""
Manual nest CRUD controller + model for QML.

Owns the Manual tab's list view — refreshes from the server, lets the user
toggle override_enabled, and deletes nests. Creation goes through
`ManualNestEditorController` (the editor window).
"""

import logging

from PySide6.QtCore import Signal, Slot, QThread

from bridge.models.manual_nest_model import ManualNestListModel
from bridge.refreshable_controller import RefreshableController

logger = logging.getLogger(__name__)


class _ManualNestRefreshWorker(QThread):
    """Background worker for fetching manual nests."""
    finished = Signal(list)

    def __init__(self, db):
        super().__init__()
        self._db = db

    def run(self):
        try:
            items = self._db.get_manual_nests() or []
            # Filter out any badly-shaped entries defensively
            cleaned = [it for it in items if isinstance(it, dict) and "id" in it]
            self.finished.emit(cleaned)
        except Exception:
            logger.exception("Failed to refresh manual nests")
            self.finished.emit([])


class ManualNestController(RefreshableController):
    """CRUD controller for manual nests.

    The ListView in the Manual tab binds to `model`. Override toggles,
    deletes, and (eventually) edits go through the slots here.
    """
    operationFailed = Signal(str)

    def __init__(self, app_ctrl, nesting_ctrl=None, parent=None):
        super().__init__(app_ctrl, ManualNestListModel(), parent)
        # NestingController reference — used to route "Send to Queue"
        # through the same DXF-gen / upload / create-job pipeline the
        # auto-nest path uses. Optional so tests can instantiate this
        # controller standalone.
        self._nesting_ctrl = nesting_ctrl

    def _create_refresh_worker(self):
        return _ManualNestRefreshWorker(self._app.db)

    def _can_refresh(self) -> bool:
        # Only hit the server if the api_client supports it. Legacy
        # sqlite-only installations don't have /manual-nests endpoints.
        return hasattr(self._app.db, "get_manual_nests")

    # ------------------------------------------------------------------

    @Slot(int, result=int)
    def nestIdAtRow(self, row: int) -> int:
        item = self._model.getItemAtRow(row)
        return int(item["id"]) if item else -1

    @Slot(int, bool, result=bool)
    def setOverrideEnabled(self, row: int, enabled: bool) -> bool:
        item = self._model.getItemAtRow(row)
        if not item:
            return False

        # Optimistic local update so the checkbox reflects the change instantly
        idx = self._model.index(row, 0)
        self._model.setData(idx, enabled, ManualNestListModel.OverrideEnabledRole)

        db = self._app.db
        try:
            db.set_manual_nest_override(int(item["id"]), bool(enabled))
        except Exception:
            logger.exception(
                "Failed to toggle override for manual nest %s", item.get("id")
            )
            # Roll the optimistic update back
            self._model.setData(idx, not enabled, ManualNestListModel.OverrideEnabledRole)
            self.operationFailed.emit(
                "Override toggle failed. You may not be connected to the server."
            )
            return False
        verb = "enabled" if enabled else "disabled"
        self.statusMessage.emit(f"Override {verb} for '{item['name']}'", 3000)
        return True

    @Slot(int, result=str)
    def sendToQueue(self, row: int) -> str:
        """Send a manual nest's sheets to the UnfnCNC queue. Returns a
        human-readable status message the QML layer can surface."""
        item = self._model.getItemAtRow(row)
        if not item:
            return "No nest selected."
        if self._nesting_ctrl is None:
            self.operationFailed.emit(
                "Can't queue — nesting controller wasn't wired up."
            )
            return ""
        db = self._app.db
        try:
            # Re-fetch for a guaranteed-complete nest (list view may have
            # stale/truncated data depending on server serialization).
            nest = db.get_manual_nest(int(item["id"]))
        except Exception:
            logger.exception("Failed to fetch manual nest %s", item.get("id"))
            self.operationFailed.emit(
                "Couldn't load the nest from the server. Check your connection."
            )
            return ""
        if not nest:
            self.operationFailed.emit("That nest no longer exists on the server.")
            return ""
        msg = self._nesting_ctrl.exportManualNest(nest, False)
        self.statusMessage.emit(f"Queued '{item['name']}'", 5000)
        return msg

    @Slot(int, result=bool)
    def deleteNest(self, row: int) -> bool:
        item = self._model.getItemAtRow(row)
        if not item:
            return False
        db = self._app.db
        try:
            db.delete_manual_nest(int(item["id"]))
        except Exception:
            logger.exception("Failed to delete manual nest %s", item.get("id"))
            self.operationFailed.emit(
                "Delete failed. You may not be connected to the server."
            )
            return False
        self.refresh()
        self.statusMessage.emit(f"Deleted manual nest: {item['name']}", 3000)
        return True
