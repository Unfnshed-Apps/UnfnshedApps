"""
App lifecycle controller — initializes API client, manages connection health,
and exposes connection status to QML.
"""

import tempfile
from pathlib import Path

from PySide6.QtCore import Property, Signal

from shared.app_controller_base import AppControllerBase
from src.api_client import APIClient
from src.config import load_config, AppConfig
from src.dxf_loader import DXFLoader


class AppController(AppControllerBase):
    configChanged = Signal()

    APP_DISPLAY_NAME = "UnfnCNC"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = None
        self._dxf_loader = None

    def _create_api_client(self):
        return APIClient()

    def _load_config(self):
        return load_config()

    def _save_config(self, config):
        from src.config import save_config
        save_config(config)

    def _create_config(self, device_name, api_key, api_url, lan_ip):
        return AppConfig(
            api_url=api_url, api_key=api_key,
            device_name=device_name, lan_server_ip=lan_ip,
        )

    def initialize(self):
        self._config = load_config()
        super().initialize()

    def _on_connected(self):
        self._rebuild_dxf_loader()

    def _on_server_changed(self):
        self._rebuild_dxf_loader()

    def _rebuild_dxf_loader(self):
        dxf_cache = Path(tempfile.gettempdir()) / "UnfnCNC" / "dxf_cache"
        api_for_loader = self._api if self._connection_ok else None
        self._dxf_loader = DXFLoader(str(dxf_cache), api_for_loader)

    @Property(str, notify=configChanged)
    def machineLetter(self):
        if self._config:
            return self._config.machine_letter
        return ""

    @property
    def dxf_loader(self):
        return self._dxf_loader

    @property
    def config(self):
        return self._config
