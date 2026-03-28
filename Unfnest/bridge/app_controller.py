"""
App lifecycle controller — initializes API/DB, exposes connection status to QML.
"""

import requests as _requests

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QThread

from src.database import Database
from src.api_client import APIClient
from src.config import load_config, save_config, get_suggested_device_name, AppConfig
from src.dxf_loader import DXFLoader
from src.order_processor import OrderProcessor
from src.dxf_output import DXFOutputGenerator

from shared.app_controller_base import RETRY_INTERVAL_MS, CONN_LABELS as _CONN_LABELS


class _ConnectionWorker(QThread):
    """Runs connection checks and DXF sync off the main thread.

    Always re-evaluates the best server (localhost → LAN → remote)
    so the app upgrades to a closer connection when one becomes available.
    """
    finished = Signal(bool, dict, str, str)  # ok, sync_result, best_url, conn_type

    def __init__(self, db, dxf_loader, do_sync=False):
        super().__init__()
        self._db = db
        self._dxf_loader = dxf_loader
        self._do_sync = do_sync

    def _check_health(self, url, timeout=3):
        try:
            resp = _requests.get(f"{url}/health", headers=self._db.headers, timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    def run(self):
        sync_result = {}
        best_url = None
        conn_type = None

        # Try servers in priority order: localhost → LAN → remote
        if self._check_health(self._db.LOCAL_URL, timeout=2):
            best_url = self._db.LOCAL_URL
            conn_type = "local"
        elif self._db.lan_server_ip:
            lan_url = f"http://{self._db.lan_server_ip}:8000"
            if self._check_health(lan_url, timeout=3):
                best_url = lan_url
                conn_type = "lan"

        if not best_url:
            if self._check_health(self._db.REMOTE_URL, timeout=5):
                best_url = self._db.REMOTE_URL
                conn_type = "remote"

        ok = best_url is not None

        if ok and self._do_sync and self._dxf_loader:
            try:
                sync_result = self._dxf_loader.sync_from_server()
            except Exception:
                pass

        self.finished.emit(ok, sync_result, best_url or "", conn_type or "")


class AppController(QObject):
    connectionStatusChanged = Signal()
    statusMessage = Signal(str, int)  # message, timeout_ms
    testStatusChanged = Signal()
    setupNeededChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = None
        self._using_api = False
        self._connection_ok = False
        self._connection_status = ""
        self._dxf_loader = None
        self._processor = None
        self._output_gen = None
        self._conn_worker = None
        self._test_status = ""
        self._test_status_ok = False

        # Background retry timer
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(RETRY_INTERVAL_MS)
        self._retry_timer.timeout.connect(self._retry_connection)

    def initialize(self):
        """Initialize API/DB connection. Call after QML engine is ready."""
        try:
            self._db = APIClient()
            self._db.base_url  # triggers URL resolution
            self._using_api = True
        except Exception:
            self._db = Database()
            self._using_api = False

        # Verify the connection actually works (blocking on startup is OK —
        # the UI hasn't loaded yet)
        if self._using_api:
            self._connection_ok = self._test_connection_sync()
        else:
            self._connection_ok = True  # local DB always works

        api_client = self._db if self._using_api and self._connection_ok else None
        self._rebuild_loaders(api_client)

        # Kick off initial DXF sync in background
        if self._using_api and self._connection_ok:
            self._run_background_sync()
        self._output_gen = DXFOutputGenerator()
        self._update_connection_status()

        # Start retry timer if using API (checks whether connected or not)
        if self._using_api:
            self._retry_timer.start()

    def _rebuild_loaders(self, api_client=None):
        """Rebuild DXF loader and order processor for the current connection."""
        self._dxf_loader = DXFLoader(api_client=api_client)
        self._processor = OrderProcessor(self._db, self._dxf_loader)

    def _test_connection_sync(self):
        """Synchronous connection test — only for startup before UI is shown."""
        try:
            url = f"{self._db.base_url}/health"
            resp = _requests.get(url, headers=self._db.headers, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _retry_connection(self):
        """Periodic background check — runs off the main thread."""
        if self._conn_worker and self._conn_worker.isRunning():
            return  # previous check still in progress, skip this cycle

        do_sync = not self._connection_ok  # sync if we were previously disconnected
        self._conn_worker = _ConnectionWorker(self._db, self._dxf_loader, do_sync=do_sync)
        self._conn_worker.finished.connect(self._on_retry_finished)
        self._conn_worker.start()

    def _on_retry_finished(self, ok, sync_result, best_url, conn_type):
        """Handle result from background connection check."""
        was_ok = self._connection_ok
        self._connection_ok = ok

        # Upgrade to a closer server if one was found
        if ok and best_url and best_url != self._db.base_url:
            old_type = self._db.connection_info['type'] or "unknown"
            self._db.set_server(best_url, conn_type)
            self._rebuild_loaders(self._db)
            old_label = _CONN_LABELS.get(old_type, old_type)
            new_label = _CONN_LABELS.get(conn_type, conn_type)
            self.statusMessage.emit(f"Upgraded connection: {old_label} → {new_label}", 5000)
            self._update_connection_status()
            return

        if ok == was_ok:
            return  # no change

        if ok and not was_ok:
            # Just came back online
            self._db.set_server(best_url, conn_type)
            self._rebuild_loaders(self._db)
            if sync_result.get("downloaded", 0) > 0 or sync_result.get("deleted", 0) > 0:
                print(f"DXF sync: {sync_result['downloaded']} downloaded, {sync_result['deleted']} removed, {sync_result['unchanged']} unchanged")
            self.statusMessage.emit("Connection restored", 5000)

        self._update_connection_status()

    def _run_background_sync(self):
        """Run DXF sync in a background thread."""
        if self._conn_worker and self._conn_worker.isRunning():
            return
        self._conn_worker = _ConnectionWorker(self._db, self._dxf_loader, do_sync=True)
        self._conn_worker.finished.connect(self._on_sync_finished)
        self._conn_worker.start()

    def _on_sync_finished(self, ok, sync_result, best_url, conn_type):
        """Handle result from background DXF sync."""
        # Update connection if a better server was found during sync
        if ok and best_url and best_url != self._db.base_url:
            self._db.set_server(best_url, conn_type)
            self._rebuild_loaders(self._db)
            self._update_connection_status()
        if sync_result.get("downloaded", 0) > 0 or sync_result.get("deleted", 0) > 0:
            self.statusMessage.emit(
                f"Synced {sync_result.get('downloaded', 0)} DXF file(s) from server", 3000
            )

    def _update_connection_status(self):
        if self._using_api:
            config = load_config()
            conn_info = self._db.connection_info
            if self._connection_ok:
                label = _CONN_LABELS.get(conn_info['type'], conn_info['type'])
                self._connection_status = f"Connected: {label} ({conn_info['url']}) | Device: {config.device_name}"
            else:
                self._connection_status = "Unable to connect to Unfnest Database"
        else:
            self._connection_status = "Using local database (offline mode)"
        self.connectionStatusChanged.emit()

    @Property(str, notify=connectionStatusChanged)
    def connectionStatus(self):
        return self._connection_status

    @Property(bool, notify=connectionStatusChanged)
    def usingApi(self):
        return self._using_api

    @Property(bool, notify=connectionStatusChanged)
    def connectionOk(self):
        return self._connection_ok

    @property
    def db(self):
        return self._db

    @property
    def dxf_loader(self):
        return self._dxf_loader

    @property
    def processor(self):
        return self._processor

    @property
    def output_gen(self):
        return self._output_gen

    @property
    def api_client(self):
        return self._db if self._using_api else None

    @Property(bool, notify=setupNeededChanged)
    def setupNeeded(self):
        return not load_config().is_configured

    @Property(str, notify=testStatusChanged)
    def testStatus(self):
        return self._test_status

    @Property(bool, notify=testStatusChanged)
    def testStatusOk(self):
        return self._test_status_ok

    @Slot(result=str)
    def suggestedDeviceName(self):
        return get_suggested_device_name()

    @Slot(result=str)
    def currentDeviceName(self):
        return load_config().device_name

    @Slot(result=str)
    def currentApiKey(self):
        return load_config().api_key

    @Slot(result=str)
    def currentApiUrl(self):
        return load_config().api_url

    @Slot(result=str)
    def currentLanIp(self):
        return load_config().lan_server_ip

    @Slot()
    def testConnection(self):
        """Test API connection using auto-detection (synchronous, user-initiated)."""
        from PySide6.QtWidgets import QApplication

        self._test_status = "Detecting server..."
        self._test_status_ok = False
        self.testStatusChanged.emit()
        QApplication.processEvents()

        config = load_config()
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
        config = AppConfig(
            api_url=api_url,
            api_key=api_key,
            device_name=device_name,
            lan_server_ip=lan_ip,
        )
        save_config(config)
        self.setupNeededChanged.emit()
        self._reconnect_api()

    def _reconnect_api(self):
        try:
            self._db = APIClient()
            self._using_api = True
            self._rebuild_loaders(self._db)

            self.statusMessage.emit("Connecting...", 0)
            self._update_connection_status()

            # Test connection in background
            self._conn_worker = _ConnectionWorker(self._db, self._dxf_loader, do_sync=True)
            self._conn_worker.finished.connect(self._on_reconnect_finished)
            self._conn_worker.start()

            # Ensure retry timer is running
            if not self._retry_timer.isActive():
                self._retry_timer.start()
        except Exception as e:
            self._connection_ok = False
            self._update_connection_status()
            self.statusMessage.emit(f"Connection failed: {e}", 5000)

    def _on_reconnect_finished(self, ok, sync_result, best_url, conn_type):
        """Handle result from reconnection attempt."""
        self._connection_ok = ok
        if ok and best_url:
            self._db.set_server(best_url, conn_type)
            self._rebuild_loaders(self._db)
        self._update_connection_status()

        if ok:
            self.statusMessage.emit(f"Connected to API at {self._db.base_url}", 5000)
        else:
            self.statusMessage.emit("Unable to connect to Unfnest Database", 5000)

    def close(self):
        self._retry_timer.stop()
        if self._db:
            self._db.close()
