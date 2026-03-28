"""
Shopify credentials controller — load/save/test/clear settings via API client.
"""

from PySide6.QtCore import QObject, Property, Signal, Slot

API_VERSION_OPTIONS = [
    "2024-01", "2024-04", "2024-07", "2024-10",
    "2025-01", "2025-04", "2025-07", "2025-10",
    "2026-01",
]


class ShopifyController(QObject):
    storeUrlChanged = Signal()
    clientIdChanged = Signal()
    clientSecretChanged = Signal()
    apiVersionChanged = Signal()
    statusTextChanged = Signal()
    statusOkChanged = Signal()
    isConfiguredChanged = Signal()

    settingsSaved = Signal()
    settingsCleared = Signal()
    statusMessage = Signal(str, int)  # message, timeout_ms
    operationFailed = Signal(str)

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._store_url = ""
        self._client_id = ""
        self._client_secret = ""
        self._api_version = "2026-01"
        self._status_text = "Not connected"
        self._status_ok = False
        self._is_configured = False

    # ── Properties ──────────────────────────────────────────────

    @Property(str, notify=storeUrlChanged)
    def storeUrl(self):
        return self._store_url

    @Property(str, notify=clientIdChanged)
    def clientId(self):
        return self._client_id

    @Property(str, notify=clientSecretChanged)
    def clientSecret(self):
        return self._client_secret

    @Property(str, notify=apiVersionChanged)
    def apiVersion(self):
        return self._api_version

    @Property(str, notify=statusTextChanged)
    def statusText(self):
        return self._status_text

    @Property(bool, notify=statusOkChanged)
    def statusOk(self):
        return self._status_ok

    @Property(bool, notify=isConfiguredChanged)
    def isConfigured(self):
        return self._is_configured

    @Property("QVariantList", constant=True)
    def apiVersionOptions(self):
        return API_VERSION_OPTIONS

    # ── Helpers ─────────────────────────────────────────────────

    def _set_status(self, ok, text):
        changed = False
        if self._status_ok != ok:
            self._status_ok = ok
            self.statusOkChanged.emit()
            changed = True
        if self._status_text != text:
            self._status_text = text
            self.statusTextChanged.emit()
            changed = True
        return changed

    def _update_is_configured(self):
        configured = bool(self._store_url and self._client_id and self._client_secret)
        if self._is_configured != configured:
            self._is_configured = configured
            self.isConfiguredChanged.emit()

    @staticmethod
    def _clean_url(url):
        return url.strip().replace("https://", "").replace("http://", "").rstrip("/")

    # ── Slots ───────────────────────────────────────────────────

    @Slot()
    def loadSettings(self):
        """Load Shopify credentials from server via API."""
        api = self._app.api
        if not api:
            self._set_status(False, "No server connection")
            return
        try:
            result = api.get_shopify_settings()
            self._store_url = result.get("store_url", "") or ""
            self.storeUrlChanged.emit()
            self._client_id = result.get("client_id", "") or ""
            self.clientIdChanged.emit()
            self._client_secret = result.get("client_secret", "") or ""
            self.clientSecretChanged.emit()
            if result.get("api_version"):
                self._api_version = result["api_version"]
                self.apiVersionChanged.emit()
            if self._store_url and self._client_id and self._client_secret:
                self._set_status(True, f"Connected to {self._store_url}")
            else:
                self._set_status(False, "Not connected")
            self._update_is_configured()
        except Exception as e:
            self._set_status(False, f"Error loading settings: {e}")

    @Slot(str, str, str, str)
    def saveSettings(self, store_url, client_id, client_secret, api_version):
        """Save credentials to server via API."""
        store_url = self._clean_url(store_url)
        client_id = client_id.strip()
        client_secret = client_secret.strip()

        if not store_url or not client_id or not client_secret:
            self.operationFailed.emit("Please enter Store URL, Client ID, and Client Secret.")
            return

        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection.")
            return
        try:
            api.save_shopify_settings(store_url, client_id, client_secret, api_version)
            self._store_url = store_url
            self.storeUrlChanged.emit()
            self._client_id = client_id
            self.clientIdChanged.emit()
            self._client_secret = client_secret
            self.clientSecretChanged.emit()
            self._api_version = api_version
            self.apiVersionChanged.emit()
            self._set_status(True, f"Connected to {store_url}")
            self._update_is_configured()
            self.settingsSaved.emit()
            self.statusMessage.emit("Shopify settings saved", 3000)
        except Exception as e:
            self.operationFailed.emit(f"Failed to save settings: {e}")

    @Slot(str, str, str, str)
    def testConnection(self, store_url, client_id, client_secret, api_version):
        """Test Shopify connection with given credentials (server-side test)."""
        store_url = self._clean_url(store_url)
        client_id = client_id.strip()
        client_secret = client_secret.strip()

        if not store_url or not client_id or not client_secret:
            self.operationFailed.emit("Please enter Store URL, Client ID, and Client Secret.")
            return

        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection.")
            return

        self._set_status(False, "Testing connection...")
        try:
            result = api.test_shopify_connection(store_url, client_id, client_secret, api_version)
            if result.get("success"):
                shop_name = result.get("shop_name", store_url)
                self._set_status(True, f"Connected to: {shop_name}")
                self.statusMessage.emit(f"Connection successful: {shop_name}", 5000)
            else:
                error_msg = result.get("error", "Connection failed")
                self._set_status(False, "Connection failed")
                self.operationFailed.emit(f"Could not connect: {error_msg}")
        except Exception as e:
            self._set_status(False, "Connection error")
            self.operationFailed.emit(f"Connection error: {e}")

    @Slot()
    def clearSettings(self):
        """Clear all Shopify credentials via API."""
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection.")
            return
        try:
            api.clear_shopify_settings()
            self._store_url = ""
            self.storeUrlChanged.emit()
            self._client_id = ""
            self.clientIdChanged.emit()
            self._client_secret = ""
            self.clientSecretChanged.emit()
            self._set_status(False, "Not connected")
            self._update_is_configured()
            self.settingsCleared.emit()
            self.statusMessage.emit("Shopify settings cleared", 3000)
        except Exception as e:
            self.operationFailed.emit(f"Failed to clear settings: {e}")
