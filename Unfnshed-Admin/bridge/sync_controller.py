"""
Sync controller — auto-sync settings, manual trigger via API client.
"""

from datetime import datetime

from PySide6.QtCore import QObject, Property, Signal, Slot, QThread


class SyncWorker(QThread):
    """Background thread that triggers a server-side sync via API."""

    finished = Signal(int, int)  # (synced_count, error_count)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self._api = api

    def run(self):
        try:
            self.progress.emit("Triggering sync on server...")
            result = self._api.trigger_sync()
            synced = result.get("synced_count", 0)
            errors = result.get("error_count", 0)
            self.finished.emit(synced, errors)
        except Exception as e:
            self.error.emit(str(e))


class SyncController(QObject):
    autoSyncEnabledChanged = Signal()
    syncIntervalChanged = Signal()
    lastSyncChanged = Signal()
    syncStatusChanged = Signal()
    isSyncingChanged = Signal()

    syncCompleted = Signal()
    autoSyncChanged = Signal(bool, int)  # (enabled, interval_minutes)
    statusMessage = Signal(str, int)
    operationFailed = Signal(str)

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._auto_sync_enabled = False
        self._sync_interval = 60
        self._last_sync = "Never"
        self._sync_status = ""
        self._is_syncing = False
        self._sync_worker = None

    # ── Properties ──────────────────────────────────────────────

    @Property(bool, notify=autoSyncEnabledChanged)
    def autoSyncEnabled(self):
        return self._auto_sync_enabled

    @Property(int, notify=syncIntervalChanged)
    def syncInterval(self):
        return self._sync_interval

    @Property(str, notify=lastSyncChanged)
    def lastSync(self):
        return self._last_sync

    @Property(str, notify=syncStatusChanged)
    def syncStatus(self):
        return self._sync_status

    @Property(bool, notify=isSyncingChanged)
    def isSyncing(self):
        return self._is_syncing

    # ── Slots ───────────────────────────────────────────────────

    @Slot()
    def loadSettings(self):
        """Load sync settings from the server via API."""
        api = self._app.api
        if not api:
            return
        try:
            result = api.get_sync_settings()
            self._auto_sync_enabled = result.get("auto_sync", False)
            self.autoSyncEnabledChanged.emit()
            self._sync_interval = result.get("sync_interval_minutes", 60)
            self.syncIntervalChanged.emit()
            last_sync = result.get("last_sync")
            if last_sync:
                # Server returns ISO format string
                self._last_sync = last_sync
            else:
                self._last_sync = "Never"
            self.lastSyncChanged.emit()
        except Exception as e:
            self._sync_status = f"Error loading settings: {e}"
            self.syncStatusChanged.emit()

    @Slot(bool)
    def setAutoSync(self, enabled):
        """Toggle auto-sync and persist via API."""
        self._auto_sync_enabled = enabled
        self.autoSyncEnabledChanged.emit()
        self._save_sync_settings()
        self.autoSyncChanged.emit(enabled, self._sync_interval)

    @Slot(int)
    def setInterval(self, minutes):
        """Set sync interval and persist via API."""
        self._sync_interval = minutes
        self.syncIntervalChanged.emit()
        self._save_sync_settings()
        if self._auto_sync_enabled:
            self.autoSyncChanged.emit(True, minutes)

    @Slot()
    def syncNow(self):
        """Trigger an immediate sync on the server."""
        if self._is_syncing:
            self.statusMessage.emit("Sync already in progress", 3000)
            return
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection.")
            return
        self._is_syncing = True
        self.isSyncingChanged.emit()
        self._sync_status = "Starting sync..."
        self.syncStatusChanged.emit()

        self._sync_worker = SyncWorker(api)
        self._sync_worker.finished.connect(self._on_sync_finished)
        self._sync_worker.error.connect(self._on_sync_error)
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.start()

    @Slot()
    def refreshLastSync(self):
        """Refresh the last sync timestamp from server."""
        api = self._app.api
        if not api:
            return
        try:
            result = api.get_sync_settings()
            last_sync = result.get("last_sync")
            if last_sync:
                self._last_sync = last_sync
            else:
                self._last_sync = "Never"
            self.lastSyncChanged.emit()
        except Exception:
            pass

    # ── Private ─────────────────────────────────────────────────

    def _save_sync_settings(self):
        api = self._app.api
        if not api:
            return
        try:
            api.save_sync_settings(self._auto_sync_enabled, self._sync_interval)
        except Exception as e:
            self.operationFailed.emit(f"Failed to save sync settings: {e}")

    def _on_sync_progress(self, message):
        self._sync_status = message
        self.syncStatusChanged.emit()

    def _on_sync_finished(self, synced, errors):
        self._is_syncing = False
        self.isSyncingChanged.emit()
        now = datetime.now()
        self._last_sync = now.strftime("%Y-%m-%d %H:%M:%S")
        self.lastSyncChanged.emit()
        if errors > 0:
            self._sync_status = f"Synced {synced} orders with {errors} errors"
        else:
            self._sync_status = f"Synced {synced} orders successfully"
        self.syncStatusChanged.emit()
        self.syncCompleted.emit()
        self.statusMessage.emit(self._sync_status, 5000)

    def _on_sync_error(self, error):
        self._is_syncing = False
        self.isSyncingChanged.emit()
        self._sync_status = f"Sync failed: {error}"
        self.syncStatusChanged.emit()
        self.operationFailed.emit(f"Sync failed:\n{error}")
