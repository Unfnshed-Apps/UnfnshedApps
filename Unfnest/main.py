#!/usr/bin/env python3
"""
QML entry point for the Unfnest nesting application.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine

from bridge.app_controller import AppController
from bridge.component_controller import ComponentController
from bridge.product_controller import ProductController
from bridge.nesting_controller import NestingController
from bridge.settings_controller import SettingsController
from bridge.replenishment_controller import ReplenishmentController
from bridge.machine_controller import MachineController
from bridge.dxf_preview_item import DXFPreviewItem
from bridge.sheet_preview_item import SheetPreviewItem
from bridge.utilization_controller import UtilizationController


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("NestingApp")
    app.setApplicationName("Unfnest")

    # Core app controller — manages DB/API lifecycle
    app_ctrl = AppController()
    app_ctrl.initialize()

    # Feature controllers
    settings_ctrl = SettingsController()
    component_ctrl = ComponentController(app_ctrl)
    product_ctrl = ProductController(app_ctrl)
    nesting_ctrl = NestingController(app_ctrl, settings_ctrl)
    replenishment_ctrl = ReplenishmentController(app_ctrl)
    machine_ctrl = MachineController(app_ctrl)

    # Wire up cross-controller references
    nesting_ctrl.set_product_controller(product_ctrl)
    nesting_ctrl.set_component_controller(component_ctrl)
    replenishment_ctrl.set_nesting_controller(nesting_ctrl)

    # Set shared references for QML items
    DXFPreviewItem.set_shared_dxf_loader(app_ctrl.dxf_loader)
    SheetPreviewItem.set_shared_nesting_controller(nesting_ctrl)

    # Register custom QML types
    DXFPreviewItem.register()
    SheetPreviewItem.register()

    # QML engine
    engine = QQmlApplicationEngine()

    # Expose controllers as context properties
    ctx = engine.rootContext()
    ctx.setContextProperty("appController", app_ctrl)
    ctx.setContextProperty("componentController", component_ctrl)
    ctx.setContextProperty("productController", product_ctrl)
    ctx.setContextProperty("nestingController", nesting_ctrl)
    ctx.setContextProperty("settingsController", settings_ctrl)
    ctx.setContextProperty("replenishmentController", replenishment_ctrl)

    ctx.setContextProperty("machineController", machine_ctrl)

    utilization_ctrl = UtilizationController()
    ctx.setContextProperty("utilizationController", utilization_ctrl)

    # Load QML
    qml_dir = Path(__file__).parent / "qml"
    engine.addImportPath(str(qml_dir))
    engine.load(str(qml_dir / "Main.qml"))

    if not engine.rootObjects():
        print("Failed to load QML")
        sys.exit(1)

    # Initial data load
    component_ctrl.refresh()
    product_ctrl.refresh()
    machine_ctrl.refresh()

    ret = app.exec()
    app_ctrl.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
