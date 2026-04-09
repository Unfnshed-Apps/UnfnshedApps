"""
App lifecycle controller for Unfnship.
"""

from PySide6.QtCore import Slot

from shared.app_controller_base import AppControllerBase
from src.api_client import APIClient
from src.config import load_config, save_config, AppConfig


class AppController(AppControllerBase):
    APP_DISPLAY_NAME = "Unfnship"

    def _create_api_client(self):
        return APIClient()

    def _load_config(self):
        return load_config()

    def _save_config(self, config):
        save_config(config)

    def _create_config(self, device_name, api_key, api_url, lan_ip):
        return AppConfig(
            api_url=api_url, api_key=api_key,
            device_name=device_name, lan_server_ip=lan_ip,
        )

    @Slot(str, result=str)
    def getConfigValue(self, key):
        """Read a config value by field name."""
        config = load_config()
        return getattr(config, key, "")

    @Slot(str, str)
    def setConfigValue(self, key, value):
        """Write a config value by field name and save."""
        config = load_config()
        if hasattr(config, key):
            setattr(config, key, value)
            save_config(config)
