"""
Base class for controllers that expose a QAbstractListModel and
refresh it via a background QThread worker.
"""

import logging

from PySide6.QtCore import QObject, Property, Signal, Slot

logger = logging.getLogger(__name__)


class RefreshableController(QObject):
    """Base for controllers with a list model and background refresh.

    Subclasses must:
      - Call super().__init__(app_ctrl, model, parent)
      - Implement _create_refresh_worker() -> QThread with finished(list) signal
      - Optionally override _can_refresh() for extra guards
    """
    modelChanged = Signal()
    statusMessage = Signal(str, int)

    def __init__(self, app_ctrl, model, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._model = model
        self._refresh_worker = None

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    def _create_refresh_worker(self):
        """Create and return a QThread with a finished(list) signal.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _can_refresh(self) -> bool:
        """Extra guard before refreshing. Override to add checks."""
        return True

    @Slot()
    def refresh(self):
        if not self._app.db:
            return
        if not self._can_refresh():
            return
        if self._refresh_worker and self._refresh_worker.isRunning():
            return
        self._refresh_worker = self._create_refresh_worker()
        self._refresh_worker.finished.connect(self._on_refresh_finished)
        self._refresh_worker.start()

    def _on_refresh_finished(self, items):
        self._model.resetItems(items)
