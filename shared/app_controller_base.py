"""
Base app controller with connection lifecycle management.

Provides the common connection status tracking, retry timer,
server upgrade logic, setup/test slots, and reconnection flow.
Apps subclass this and override _create_api_client() and
_on_connected() to wire up their specific controllers.
"""

import requests as _requests

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from .connection_worker import ConnectionWorker

RETRY_INTERVAL_MS = 30_000  # 30 seconds
CONN_LABELS = {"local": "Local", "lan": "LAN", "remote": "Remote", "configured": "Configured"}


class AppControllerBase(QObject):
    connectionStatusChanged = Signal()
    statusMessage = Signal(str, int)  # message, timeout_ms
    setupNeededChanged = Signal()
    testStatusChanged = Signal()

    # Subclasses set this for the disconnected status message
    APP_DISPLAY_NAME = "Unfnshed"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._api = None
        self._connection_ok = False
        self._connection_status = ""
        self._conn_worker = None
        self._test_status = ""
        self._test_status_ok = False

        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(RETRY_INTERVAL_MS)
        self._retry_timer.timeout.connect(self._retry_connection)

    def _create_api_client(self):
        """Create and return the app-specific APIClient instance.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _load_config(self):
        """Load and return the app-specific config.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _save_config(self, config):
        """Save the app-specific config.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _create_config(self, device_name, api_key, api_url, lan_ip):
        """Create and return an app-specific config object from setup dialog values.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _on_connected(self):
        """Called when a connection is first established or restored.
        Override to rebuild loaders, sync data, etc.
        """
        pass

    def _on_server_changed(self):
        """Called when the active server URL changes (upgrade/downgrade).
        Override to rebuild loaders that depend on the server URL.
        """
        pass

    def initialize(self):
        """Initialize API connection. Call after QApplication is created."""
        try:
            self._api = self._create_api_client()
            self._api.base_url  # triggers URL resolution
        except Exception:
            self._api = None

        self._connection_ok = self._test_connection_sync()

        if self._connection_ok:
            self._on_connected()

        self._update_connection_status()
        self._retry_timer.start()

    def _test_connection_sync(self):
        """Synchronous connection test -- only for startup before UI is shown."""
        if not self._api:
            return False
        try:
            url = f"{self._api.base_url}/health"
            resp = _requests.get(url, headers=self._api.headers, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _retry_connection(self):
        """Periodic background check -- runs off the main thread."""
        if self._conn_worker and self._conn_worker.isRunning():
            return
        if not self._api:
            return
        self._conn_worker = ConnectionWorker(self._api)
        self._conn_worker.finished.connect(self._on_retry_finished)
        self._conn_worker.start()

    def _on_retry_finished(self, ok, best_url, conn_type):
        was_ok = self._connection_ok
        self._connection_ok = ok

        # Upgrade to a closer server if one was found
        if ok and best_url and best_url != self._api.base_url:
            old_type = self._api.connection_info['type'] or "unknown"
            self._api.set_server(best_url, conn_type)
            self._on_server_changed()
            old_label = CONN_LABELS.get(old_type, old_type)
            new_label = CONN_LABELS.get(conn_type, conn_type)
            self.statusMessage.emit(f"Upgraded connection: {old_label} \u2192 {new_label}", 5000)
            self._update_connection_status()
            return

        if ok == was_ok:
            return  # no change

        if ok and not was_ok:
            self._api.set_server(best_url, conn_type)
            self._on_server_changed()
            self._on_connected()
            self.statusMessage.emit("Connection restored", 5000)

        self._update_connection_status()

    def _update_connection_status(self):
        if self._api and self._connection_ok:
            config = self._load_config()
            conn_info = self._api.connection_info
            label = CONN_LABELS.get(conn_info.get("type", ""), conn_info.get("type", "unknown"))
            self._connection_status = (
                f"Connected: {label} ({conn_info['url']}) | "
                f"Device: {config.device_name}"
            )
        else:
            self._connection_status = f"Unable to connect to {self.APP_DISPLAY_NAME} Database"
        self.connectionStatusChanged.emit()

    # ---- QML Properties ----

    @Property(str, notify=connectionStatusChanged)
    def connectionStatus(self):
        return self._connection_status

    @Property(bool, notify=connectionStatusChanged)
    def connectionOk(self):
        return self._connection_ok

    @property
    def api(self):
        return self._api

    @Property(bool, notify=setupNeededChanged)
    def setupNeeded(self):
        return not self._load_config().is_configured

    @Property(str, notify=testStatusChanged)
    def testStatus(self):
        return self._test_status

    @Property(bool, notify=testStatusChanged)
    def testStatusOk(self):
        return self._test_status_ok

    @Slot(result=str)
    def suggestedDeviceName(self):
        from .config_base import get_suggested_device_name
        return get_suggested_device_name()

    @Slot(result=str)
    def currentDeviceName(self):
        return self._load_config().device_name

    @Slot(result=str)
    def currentApiKey(self):
        return self._load_config().api_key

    @Slot(result=str)
    def currentApiUrl(self):
        return self._load_config().api_url

    @Slot(result=str)
    def currentLanIp(self):
        return self._load_config().lan_server_ip

    @Slot()
    def testConnection(self):
        """Test API connection using auto-detection (synchronous, user-initiated)."""
        from PySide6.QtWidgets import QApplication

        self._test_status = "Detecting server..."
        self._test_status_ok = False
        self.testStatusChanged.emit()
        QApplication.processEvents()

        config = self._load_config()
        api_key = config.api_key
        headers = {"X-API-Key": api_key} if api_key else {}

        urls_to_try = [("http://127.0.0.1:8000", "Local")]
        if config.lan_server_ip:
            urls_to_try.append((f"http://{config.lan_server_ip}:8000", "LAN"))
        urls_to_try.append(("https://api.gradschoolalternative.com", "Remote"))

        for url, label in urls_to_try:
            self._test_status = f"Trying {label} ({url})..."
            self.testStatusChanged.emit()
            QApplication.processEvents()
            try:
                resp = _requests.get(f"{url}/health", headers=headers, timeout=3)
                if resp.status_code == 200:
                    self._test_status = f"Connected: {label} ({url})"
                    self._test_status_ok = True
                    self.testStatusChanged.emit()
                    return
            except Exception:
                continue

        self._test_status = "Could not connect to any server"
        self._test_status_ok = False
        self.testStatusChanged.emit()

    @Slot(str, str, str, str)
    def saveSetupSettings(self, device_name, api_key, api_url, lan_ip):
        """Save setup settings and reconnect."""
        config = self._create_config(device_name, api_key, api_url, lan_ip)
        self._save_config(config)
        self.setupNeededChanged.emit()
        self._reconnect()

    def _reconnect(self):
        try:
            self._api = self._create_api_client()
            self._connection_ok = False
            self._update_connection_status()
            self.statusMessage.emit("Connecting...", 0)

            self._conn_worker = ConnectionWorker(self._api)
            self._conn_worker.finished.connect(self._on_reconnect_finished)
            self._conn_worker.start()

            if not self._retry_timer.isActive():
                self._retry_timer.start()
        except Exception as e:
            self._connection_ok = False
            self._update_connection_status()
            self.statusMessage.emit(f"Connection failed: {e}", 5000)

    def _on_reconnect_finished(self, ok, best_url, conn_type):
        self._connection_ok = ok
        if ok and best_url:
            self._api.set_server(best_url, conn_type)
            self._on_server_changed()
            self._on_connected()
        self._update_connection_status()

        if ok:
            self.statusMessage.emit(f"Connected to API at {self._api.base_url}", 5000)
        else:
            self.statusMessage.emit(f"Unable to connect to {self.APP_DISPLAY_NAME} Database", 5000)

    def close(self):
        self._retry_timer.stop()
        if self._api:
            self._api.close()
