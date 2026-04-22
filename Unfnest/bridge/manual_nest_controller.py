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

    def __init__(self, app_ctrl, parent=None):
        super().__init__(app_ctrl, ManualNestListModel(), parent)

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
