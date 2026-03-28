import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "tabs"
import "dialogs"

ApplicationWindow {
    id: root
    title: "Unfnshed Admin"
    width: 900
    height: 700
    minimumWidth: 800
    minimumHeight: 500
    visible: true

    // ── Menu Bar ───────────────────────────────────────────
    menuBar: MenuBar {
        Menu {
            title: "File"
            Action {
                text: "Refresh"
                shortcut: "Ctrl+R"
                onTriggered: {
                    shopifyController.loadSettings()
                    syncController.loadSettings()
                    orderController.refresh()
                }
            }
            MenuSeparator {}
            Action {
                text: "Quit"
                shortcut: "Ctrl+Q"
                onTriggered: Qt.quit()
            }
        }
        Menu {
            title: "Sync"
            Action {
                text: "Sync Now"
                shortcut: "Ctrl+S"
                onTriggered: syncController.syncNow()
            }
        }
        Menu {
            title: "Help"
            Action {
                text: "About"
                onTriggered: aboutDialog.open()
            }
        }
    }

    // ── Main Content ───────────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabBar {
            id: tabBar
            Layout.fillWidth: true

            TabButton { text: "Shopify Settings" }
            TabButton { text: "Sync Control" }
            TabButton { text: "Orders" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            ShopifySettingsTab {}
            SyncControlTab {}
            OrdersTab {}
        }
    }

    // ── Footer / Status Bar ────────────────────────────────
    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            spacing: 12

            // DB status indicator
            RowLayout {
                spacing: 4
                Rectangle {
                    width: 8; height: 8; radius: 4
                    color: appController.connectionOk ? "#4CAF50" : "#f44336"
                }
                Label {
                    text: appController.connectionStatus
                    font.pixelSize: 12
                }
            }

            // Transient status message
            Label {
                id: statusLabel
                Layout.fillWidth: true
                elide: Text.ElideRight
                color: palette.placeholderText
                font.pixelSize: 12
            }

            // Connection type
            Label {
                text: ""
                font.pixelSize: 12
                color: palette.placeholderText
            }
        }
    }

    // ── Signal routing ─────────────────────────────────────

    // appController status messages
    Connections {
        target: appController
        function onStatusMessage(msg, timeout) {
            statusLabel.text = msg
            if (timeout > 0) { statusClearTimer.interval = timeout; statusClearTimer.start() }
        }
    }

    // shopifyController
    Connections {
        target: shopifyController
        function onStatusMessage(msg, timeout) {
            statusLabel.text = msg
            if (timeout > 0) { statusClearTimer.interval = timeout; statusClearTimer.start() }
        }
        function onOperationFailed(msg) {
            errorDialog.text = msg
            errorDialog.open()
        }
    }

    // syncController
    Connections {
        target: syncController
        function onStatusMessage(msg, timeout) {
            statusLabel.text = msg
            if (timeout > 0) { statusClearTimer.interval = timeout; statusClearTimer.start() }
        }
        function onOperationFailed(msg) {
            errorDialog.text = msg
            errorDialog.open()
        }
    }

    // orderController
    Connections {
        target: orderController
        function onStatusMessage(msg, timeout) {
            statusLabel.text = msg
            if (timeout > 0) { statusClearTimer.interval = timeout; statusClearTimer.start() }
        }
        function onOperationFailed(msg) {
            errorDialog.text = msg
            errorDialog.open()
        }
    }

    // ── Timers ─────────────────────────────────────────────
    Timer {
        id: statusClearTimer
        interval: 5000
        repeat: false
        onTriggered: statusLabel.text = ""
    }

    // ── Dialogs ────────────────────────────────────────────
    Dialog {
        id: errorDialog
        title: "Error"
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 420
        standardButtons: Dialog.Ok
        property alias text: errorLabel.text

        Label {
            id: errorLabel
            wrapMode: Text.WordWrap
            width: parent.width
            color: "#e53935"
        }
    }

    Dialog {
        id: aboutDialog
        title: "About Unfnshed Admin"
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 400
        standardButtons: Dialog.Ok

        Label {
            wrapMode: Text.WordWrap
            width: parent.width
            text: "Unfnshed Admin v1.0.0\n\n" +
                  "Administration client for managing Shopify\n" +
                  "integration and order synchronization.\n\n" +
                  "Connects to the Unfnshed Server via API."
        }
    }
}
