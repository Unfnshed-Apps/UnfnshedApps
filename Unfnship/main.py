#!/usr/bin/env python3
"""
QML entry point for the Unfnship shipping application.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine

from bridge.app_controller import AppController
from bridge.shipping_controller import ShippingController


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("Unfnshed")
    app.setApplicationName("Unfnship")

    # Core app controller
    app_ctrl = AppController()
    app_ctrl.initialize()

    # Feature controllers
    shipping_ctrl = ShippingController(app_ctrl)

    # QML engine
    engine = QQmlApplicationEngine()

    ctx = engine.rootContext()
    ctx.setContextProperty("appController", app_ctrl)
    ctx.setContextProperty("shippingController", shipping_ctrl)

    # Load QML
    qml_dir = Path(__file__).parent / "qml"
    engine.addImportPath(str(qml_dir))
    engine.load(str(qml_dir / "Main.qml"))

    if not engine.rootObjects():
        print("Failed to load QML")
        sys.exit(1)

    # Initial data load
    shipping_ctrl.refresh()

    ret = app.exec()
    app_ctrl.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
