"""
App lifecycle controller for Unfnship.
"""

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
