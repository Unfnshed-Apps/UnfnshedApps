#!/usr/bin/env python3
"""
QML entry point for the Unfnventory inventory management application.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine

from bridge.app_controller import AppController
from bridge.inventory_controller import InventoryController
from bridge.product_inventory_controller import ProductInventoryController
from bridge.dxf_preview_item import DXFPreviewItem



def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("Unfnshed")
    app.setApplicationName("Unfnventory")

    # Core app controller — manages API lifecycle
    app_ctrl = AppController()
    app_ctrl.initialize()

    # Feature controllers
    inventory_ctrl = InventoryController(app_ctrl)
    product_inv_ctrl = ProductInventoryController(app_ctrl)

    # Set shared DXF loader for preview items
    DXFPreviewItem.set_shared_dxf_loader(app_ctrl.dxf_loader)
    DXFPreviewItem.register()

    # QML engine
    engine = QQmlApplicationEngine()

    # Expose controllers as context properties
    ctx = engine.rootContext()
    ctx.setContextProperty("appController", app_ctrl)
    ctx.setContextProperty("inventoryController", inventory_ctrl)
    ctx.setContextProperty("productInventoryController", product_inv_ctrl)

    # Load QML
    qml_dir = Path(__file__).parent / "qml"
    engine.addImportPath(str(qml_dir))
    engine.load(str(qml_dir / "Main.qml"))

    if not engine.rootObjects():
        print("Failed to load QML")
        sys.exit(1)

    # Initial data load
    inventory_ctrl.refresh()
    product_inv_ctrl.refresh()

    ret = app.exec()
    app_ctrl.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
