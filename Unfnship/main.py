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

    # Core app controller — created before initialize() so we can wire
    # the connection lifecycle signal to shipping_ctrl below.
    app_ctrl = AppController()

    # Feature controllers
    shipping_ctrl = ShippingController(app_ctrl)

    # Refresh shipping status (test mode + active key) whenever the
    # connection comes up — initial connect or after reconnect. This is
    # how the TEST MODE banner stays accurate across server restarts and
    # multi-tab toggle changes.
    app_ctrl.connectionStatusChanged.connect(shipping_ctrl.refreshStatus)

    # Now bring up the connection. The signal above will fire from inside
    # initialize() and trigger the first refreshStatus call.
    app_ctrl.initialize()

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
