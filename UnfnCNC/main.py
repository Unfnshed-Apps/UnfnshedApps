#!/usr/bin/env python3
"""
QML entry point for the UnfnCNC CNC operator application.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QTimer

from bridge.app_controller import AppController
from bridge.cutting_controller import CuttingController
from bridge.damage_controller import DamageController
from bridge.settings_controller import SettingsController
from bridge.sheet_preview_item import SheetPreviewItem
from bridge.clickable_preview_item import ClickablePreviewItem


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("Unfnshed")
    app.setApplicationName("UnfnCNC")

    # Core app controller
    app_ctrl = AppController()
    app_ctrl.initialize()

    # Settings controller (QML setup dialog replaces QWidgets setup_dialog)
    settings_ctrl = SettingsController()

    def _on_settings_saved():
        from src.config import load_config
        app_ctrl._config = load_config()
        app_ctrl.configChanged.emit()
        app_ctrl._reconnect()
    settings_ctrl.settingsSaved.connect(_on_settings_saved)

    # Feature controllers
    cutting_ctrl = CuttingController(app_ctrl)
    damage_ctrl = DamageController(app_ctrl)

    # Wire cross-controller signals
    cutting_ctrl.set_damage_controller(damage_ctrl)
    damage_ctrl.damageReportReady.connect(cutting_ctrl.finalizeCutWithDamage)
    damage_ctrl.damageReportCancelled.connect(cutting_ctrl.cancelCutComplete)
    settings_ctrl.settingsSaved.connect(cutting_ctrl._on_settings_refreshed)

    # Set shared references for QML-instantiated painted items
    SheetPreviewItem.set_shared_cutting_ctrl(cutting_ctrl)
    ClickablePreviewItem.set_shared_damage_ctrl(damage_ctrl)

    # Register custom QML types
    SheetPreviewItem.register()
    ClickablePreviewItem.register()

    # QML engine
    engine = QQmlApplicationEngine()

    # Expose controllers as context properties
    ctx = engine.rootContext()
    ctx.setContextProperty("appController", app_ctrl)
    ctx.setContextProperty("settingsController", settings_ctrl)
    ctx.setContextProperty("cuttingController", cutting_ctrl)
    ctx.setContextProperty("damageController", damage_ctrl)

    # Load QML
    qml_dir = Path(__file__).parent / "qml"
    engine.addImportPath(str(qml_dir))
    engine.load(str(qml_dir / "Main.qml"))

    if not engine.rootObjects():
        print("Failed to load QML")
        sys.exit(1)

    # Initial data loads
    cutting_ctrl.start()
    QTimer.singleShot(500, cutting_ctrl.refreshQueue)
    QTimer.singleShot(1000, cutting_ctrl.checkOrphanedSheets)

    # Clean up on close
    app.aboutToQuit.connect(cutting_ctrl.releaseOnClose)
    app.aboutToQuit.connect(app_ctrl.close)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
