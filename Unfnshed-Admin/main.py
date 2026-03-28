#!/usr/bin/env python3
"""
QML entry point for the Unfnshed Admin application.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine

from bridge.app_controller import AppController
from bridge.shopify_controller import ShopifyController
from bridge.sync_controller import SyncController
from bridge.order_controller import OrderController


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("Unfnshed")
    app.setApplicationName("Unfnshed Admin")

    # ── Create controllers ──────────────────────────────────
    app_ctrl = AppController()
    app_ctrl.initialize()

    shopify_ctrl = ShopifyController(app_ctrl)
    sync_ctrl = SyncController(app_ctrl)
    order_ctrl = OrderController(app_ctrl)

    # ── Wire cross-controller signals ───────────────────────
    sync_ctrl.syncCompleted.connect(order_ctrl.refresh)
    sync_ctrl.syncCompleted.connect(sync_ctrl.refreshLastSync)
    shopify_ctrl.settingsSaved.connect(lambda: shopify_ctrl.loadSettings())
    shopify_ctrl.settingsCleared.connect(lambda: shopify_ctrl.loadSettings())

    # ── QML engine ──────────────────────────────────────────
    engine = QQmlApplicationEngine()

    ctx = engine.rootContext()
    ctx.setContextProperty("appController", app_ctrl)
    ctx.setContextProperty("shopifyController", shopify_ctrl)
    ctx.setContextProperty("syncController", sync_ctrl)
    ctx.setContextProperty("orderController", order_ctrl)

    qml_dir = Path(__file__).parent / "qml"
    engine.addImportPath(str(qml_dir))
    engine.load(str(qml_dir / "Main.qml"))

    if not engine.rootObjects():
        print("Failed to load QML")
        sys.exit(1)

    # ── Initial data load ───────────────────────────────────
    shopify_ctrl.loadSettings()
    sync_ctrl.loadSettings()
    order_ctrl.refresh()

    ret = app.exec()
    app_ctrl.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
