"""
Bridge controller for CNC machine settings — exposes setup/gcode/tool config to QML.
"""

from __future__ import annotations

import json
import requests as _requests

from PySide6.QtCore import QObject, Property, Signal, Slot, QJsonValue
from PySide6.QtWidgets import QApplication

from src.config import (
    AppConfig, load_config, save_config,
    get_suggested_device_name,
    load_gcode_settings, save_gcode_settings,
    load_tool_library, save_tool_library,
    GCODE_DEFAULTS, DEFAULT_TOOL_LIBRARY,
)

MACHINE_LETTERS = [chr(i) for i in range(ord('A'), ord('H') + 1)]


class SettingsController(QObject):
    setupNeededChanged = Signal()
    testStatusChanged = Signal()
    settingsSaved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._test_status = ""
        self._test_status_ok = False

    # ---- Setup needed ----

    @Property(bool, notify=setupNeededChanged)
    def setupNeeded(self):
        return not load_config().is_configured

    # ---- Test connection ----

    @Property(str, notify=testStatusChanged)
    def testStatus(self):
        return self._test_status

    @Property(bool, notify=testStatusChanged)
    def testStatusOk(self):
        return self._test_status_ok

    @Slot()
    def testConnection(self):
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

    # ---- Current config getters ----

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

    @Slot(result=str)
    def currentMachineLetter(self):
        return load_config().machine_letter

    @Slot(result=str)
    def currentHotFolder(self):
        return load_config().hot_folder_path

    @Slot(result=list)
    def machineLetters(self):
        return MACHINE_LETTERS

    # ---- G-code settings ----

    @Slot(result=str)
    def currentGcodeSettingsJson(self):
        """Return current gcode settings as JSON string."""
        return json.dumps(load_gcode_settings())

    @Slot(result=str)
    def defaultGcodeSettingsJson(self):
        """Return default gcode settings as JSON string."""
        return json.dumps(GCODE_DEFAULTS)

    # ---- Tool library ----

    @Slot(result=str)
    def currentToolLibraryJson(self):
        """Return current tool library as JSON string."""
        return json.dumps(load_tool_library())

    @Slot(result=str)
    def defaultToolLibraryJson(self):
        """Return default tool library as JSON string."""
        return json.dumps(DEFAULT_TOOL_LIBRARY)

    # ---- Save all settings ----

    @Slot(str, str, str, str, str, str, str, str)
    def saveAllSettings(self, device_name, api_key, api_url, lan_ip,
                        machine_letter, hot_folder, gcode_json, tools_json):
        """Save all settings at once."""
        # Machine config
        config = AppConfig(
            api_url=api_url,
            api_key=api_key,
            device_name=device_name,
            machine_letter=machine_letter,
            hot_folder_path=hot_folder,
            lan_server_ip=lan_ip,
        )
        save_config(config)

        # G-code settings
        gcode = json.loads(gcode_json)
        save_gcode_settings(gcode)

        # Tool library
        tools = json.loads(tools_json)
        save_tool_library(tools)

        self.setupNeededChanged.emit()
        self.settingsSaved.emit()

    # ---- Hot folder browse ----

    @Slot(result=str)
    def browseHotFolder(self):
        """Open native folder picker and return selected path."""
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(None, "Select Hot Folder")
        return folder or ""
