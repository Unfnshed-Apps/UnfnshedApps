"""
Shopify credentials controller — load/save/test/clear settings via API client.
"""

from PySide6.QtCore import QObject, Property, Signal, Slot

def _mask_secret(secret):
    if not secret or len(secret) <= 4:
        return "****"
    return "*" * (len(secret) - 4) + secret[-4:]


API_VERSION_OPTIONS = [
    "2024-01", "2024-04", "2024-07", "2024-10",
    "2025-01", "2025-04", "2025-07", "2025-10",
    "2026-01",
]


class ShopifyController(QObject):
    storeUrlChanged = Signal()
    clientIdChanged = Signal()
    clientSecretStoredChanged = Signal()
    apiVersionChanged = Signal()
    shippoTestKeyStoredChanged = Signal()
    shippoLiveKeyStoredChanged = Signal()
    shippoUseLiveChanged = Signal()
    shipFromChanged = Signal()
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
        # Secret fields are never stored on the client in plaintext. The
        # controller only tracks whether the server has one stored and what
        # its masked display value is. The QML TextFields are write-only
        # inputs — empty by default, submitted only when the user types.
        self._client_secret_stored = False
        self._client_secret_masked = ""
        self._api_version = "2026-01"
        # Two Shippo keys + an explicit use-live toggle. The toggle is the
        # single source of truth for which key is active; the key prefix is
        # only used for inline UI validation, never for runtime mode
        # detection.
        self._shippo_test_key_stored = False
        self._shippo_test_key_masked = ""
        self._shippo_live_key_stored = False
        self._shippo_live_key_masked = ""
        self._shippo_use_live = False
        self._ship_from = {
            "name": "",
            "street1": "",
            "street2": "",
            "city": "",
            "state": "",
            "zip": "",
            "country": "US",
            "phone": "",
        }
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

    @Property(bool, notify=clientSecretStoredChanged)
    def clientSecretStored(self):
        """True when the server has a client_secret stored."""
        return self._client_secret_stored

    @Property(str, notify=clientSecretStoredChanged)
    def clientSecretMasked(self):
        """Masked display form of the stored client_secret (e.g. ****1234)."""
        return self._client_secret_masked

    @Property(str, notify=apiVersionChanged)
    def apiVersion(self):
        return self._api_version

    @Property(bool, notify=shippoTestKeyStoredChanged)
    def shippoTestKeyStored(self):
        """True when the server has a Shippo test key stored."""
        return self._shippo_test_key_stored

    @Property(str, notify=shippoTestKeyStoredChanged)
    def shippoTestKeyMasked(self):
        """Masked display form of the stored Shippo test key."""
        return self._shippo_test_key_masked

    @Property(bool, notify=shippoLiveKeyStoredChanged)
    def shippoLiveKeyStored(self):
        """True when the server has a Shippo live key stored."""
        return self._shippo_live_key_stored

    @Property(str, notify=shippoLiveKeyStoredChanged)
    def shippoLiveKeyMasked(self):
        """Masked display form of the stored Shippo live key."""
        return self._shippo_live_key_masked

    def _read_use_live(self):
        return self._shippo_use_live

    def _write_use_live(self, value):
        if self._shippo_use_live != bool(value):
            self._shippo_use_live = bool(value)
            self.shippoUseLiveChanged.emit()

    shippoUseLive = Property(
        bool, _read_use_live, _write_use_live, notify=shippoUseLiveChanged
    )

    @Property("QVariantMap", notify=shipFromChanged)
    def shipFrom(self):
        return self._ship_from

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
        configured = bool(
            self._store_url and self._client_id and self._client_secret_stored
        )
        if self._is_configured != configured:
            self._is_configured = configured
            self.isConfiguredChanged.emit()

    @staticmethod
    def _is_real_mask(masked):
        """True if a masked string represents an actual stored value.

        ``_mask_secret`` returns "****" for an empty or too-short value;
        anything longer (with identifiable trailing characters) indicates a
        real secret exists on the server.
        """
        return bool(masked) and masked != "****"

    @staticmethod
    def _clean_url(url):
        return url.strip().replace("https://", "").replace("http://", "").rstrip("/")

    # ── Slots ───────────────────────────────────────────────────

    @Slot()
    def loadSettings(self):
        """Load Shopify credentials from server via API.

        Secret fields are only tracked as "stored? + masked display" — the
        real plaintext is never sent to the client by the server and never
        populated into the QML input fields.
        """
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

            client_secret_masked = result.get("client_secret_masked", "") or ""
            self._client_secret_masked = client_secret_masked
            self._client_secret_stored = self._is_real_mask(client_secret_masked)
            self.clientSecretStoredChanged.emit()

            if result.get("api_version"):
                self._api_version = result["api_version"]
                self.apiVersionChanged.emit()

            shippo_test_masked = result.get("shippo_test_key_masked", "") or ""
            self._shippo_test_key_masked = shippo_test_masked
            self._shippo_test_key_stored = self._is_real_mask(shippo_test_masked)
            self.shippoTestKeyStoredChanged.emit()

            shippo_live_masked = result.get("shippo_live_key_masked", "") or ""
            self._shippo_live_key_masked = shippo_live_masked
            self._shippo_live_key_stored = self._is_real_mask(shippo_live_masked)
            self.shippoLiveKeyStoredChanged.emit()

            self._write_use_live(bool(result.get("shippo_use_live", False)))

            self._ship_from = {
                "name": result.get("ship_from_name", "") or "",
                "street1": result.get("ship_from_street1", "") or "",
                "street2": result.get("ship_from_street2", "") or "",
                "city": result.get("ship_from_city", "") or "",
                "state": result.get("ship_from_state", "") or "",
                "zip": result.get("ship_from_zip", "") or "",
                "country": result.get("ship_from_country", "US") or "US",
                "phone": result.get("ship_from_phone", "") or "",
                "email": result.get("ship_from_email", "") or "",
            }
            self.shipFromChanged.emit()
            if self._store_url and self._client_id and self._client_secret_stored:
                self._set_status(True, f"Connected to {self._store_url}")
            else:
                self._set_status(False, "Not connected")
            self._update_is_configured()
        except Exception as e:
            self._set_status(False, f"Error loading settings: {e}")

    @Slot("QVariantMap")
    def saveShipFrom(self, ship_from):
        """Save just the ship-from address fields."""
        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection.")
            return
        try:
            api.save_shopify_settings(
                "", "", "", self._api_version,
                ship_from={
                    "name": ship_from.get("name", "").strip(),
                    "street1": ship_from.get("street1", "").strip(),
                    "street2": ship_from.get("street2", "").strip(),
                    "city": ship_from.get("city", "").strip(),
                    "state": ship_from.get("state", "").strip(),
                    "zip": ship_from.get("zip", "").strip(),
                    "country": ship_from.get("country", "US").strip() or "US",
                    "phone": ship_from.get("phone", "").strip(),
                    "email": ship_from.get("email", "").strip(),
                },
                only_ship_from=True,
            )
            self._ship_from = {k: v for k, v in ship_from.items()}
            self.shipFromChanged.emit()
            self.statusMessage.emit("Ship-from address saved", 3000)
        except Exception as e:
            self.operationFailed.emit(f"Failed to save ship-from: {e}")

    @Slot(str, str, str, str, str, str)
    def saveSettings(self, store_url, client_id, client_secret, api_version,
                     shippo_test_key, shippo_live_key):
        """Save API credentials to server.

        ``client_secret``, ``shippo_test_key``, ``shippo_live_key`` are only
        sent to the server when the user actually typed something. Empty
        strings mean "keep the existing stored value" — the QML TextFields
        start empty and never display the stored value, so a blank field is
        never a masked round-trip.

        ``shippo_use_live`` is read from the controller property (set by the
        QML Switch with two-way binding) and is always sent.
        """
        store_url = self._clean_url(store_url)
        client_id = client_id.strip()
        client_secret = client_secret.strip()
        shippo_test_key = shippo_test_key.strip()
        shippo_live_key = shippo_live_key.strip()

        api = self._app.api
        if not api:
            self.operationFailed.emit("No server connection.")
            return

        # Reject saving with the live toggle on but no live key — neither
        # the existing stored value nor a freshly typed one. The server
        # will reject the actual rate request anyway, but failing fast
        # here gives a clearer error.
        if self._shippo_use_live and not (shippo_live_key or self._shippo_live_key_stored):
            self.operationFailed.emit(
                "Cannot enable live mode without a live key. "
                "Enter the live key first or toggle back to test mode."
            )
            return

        try:
            api.save_shopify_settings(
                store_url, client_id, client_secret, api_version,
                shippo_test_key=shippo_test_key or None,
                shippo_live_key=shippo_live_key or None,
                shippo_use_live=self._shippo_use_live,
            )
            self._store_url = store_url
            self.storeUrlChanged.emit()
            self._client_id = client_id
            self.clientIdChanged.emit()
            self._api_version = api_version
            self.apiVersionChanged.emit()

            if client_secret:
                self._client_secret_masked = _mask_secret(client_secret)
                self._client_secret_stored = True
                self.clientSecretStoredChanged.emit()
            if shippo_test_key:
                self._shippo_test_key_masked = _mask_secret(shippo_test_key)
                self._shippo_test_key_stored = True
                self.shippoTestKeyStoredChanged.emit()
            if shippo_live_key:
                self._shippo_live_key_masked = _mask_secret(shippo_live_key)
                self._shippo_live_key_stored = True
                self.shippoLiveKeyStoredChanged.emit()

            if self._client_secret_stored:
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
        """Clear Shopify credentials via API.

        Note: this only clears the Shopify credentials (store_url, client_id,
        client_secret) — Shippo keys and ship-from settings are unaffected.
        """
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
            self._client_secret_stored = False
            self._client_secret_masked = ""
            self.clientSecretStoredChanged.emit()
            self._set_status(False, "Not connected")
            self._update_is_configured()
            self.settingsCleared.emit()
            self.statusMessage.emit("Shopify settings cleared", 3000)
        except Exception as e:
            self.operationFailed.emit(f"Failed to clear settings: {e}")
