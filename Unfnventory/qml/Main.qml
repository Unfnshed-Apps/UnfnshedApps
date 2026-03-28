import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "dialogs"

ApplicationWindow {
    id: root
    title: "Unfnventory"
    width: 900
    height: 550
    minimumWidth: 800
    minimumHeight: 500
    visible: true

    // Dark mode detection
    readonly property bool darkMode: {
        let bg = palette.window
        let lum = (0.299 * bg.r + 0.587 * bg.g + 0.114 * bg.b)
        return lum < 0.5
    }

    menuBar: MenuBar {
        Menu {
            title: "File"
            Action {
                text: "Settings..."
                onTriggered: { setupDialog.firstRun = false; setupDialog.open() }
            }
            Action {
                text: "Replenishment Settings..."
                onTriggered: replSettingsDialog.open()
            }
            MenuSeparator {}
            Action {
                text: "Recalculate Forecasts"
                onTriggered: inventoryController.recalculateForecasts()
            }
            Action {
                text: "Refresh All"
                shortcut: "Ctrl+R"
                onTriggered: {
                    inventoryController.refresh()
                    productInventoryController.refresh()
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabBar {
            id: tabBar
            Layout.fillWidth: true

            TabButton { text: "Components" }
            TabButton { text: "Products" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            InventoryView {}
            ProductsView {}
        }
    }

    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8

            Label {
                id: statusLabel
                text: appController.connectionStatus
                color: appController.connectionOk ? palette.windowText : "#e53935"
                Layout.fillWidth: true
                elide: Text.ElideRight
            }

            Button {
                text: "Recalculate"
                enabled: appController.connectionOk
                onClicked: inventoryController.recalculateForecasts()
            }

            Button {
                text: "Settings"
                onClicked: { setupDialog.firstRun = false; setupDialog.open() }
            }
        }
    }

    // Shared signal handlers
    function handleStatusMessage(msg, timeout) {
        statusLabel.text = msg
        if (timeout > 0) {
            statusTimer.interval = timeout
            statusTimer.start()
        }
    }
    function handleOperationFailed(msg) {
        errorDialog.text = msg
        errorDialog.open()
    }

    // Listen for status messages from controllers
    Connections {
        target: appController
        function onStatusMessage(msg, timeout) { root.handleStatusMessage(msg, timeout) }
    }

    Connections {
        target: inventoryController
        function onStatusMessage(msg, timeout) { root.handleStatusMessage(msg, timeout) }
        function onOperationFailed(msg) { root.handleOperationFailed(msg) }
    }

    Connections {
        target: productInventoryController
        function onStatusMessage(msg, timeout) { root.handleStatusMessage(msg, timeout) }
        function onOperationFailed(msg) { root.handleOperationFailed(msg) }
    }

    Timer {
        id: statusTimer
        interval: 5000
        repeat: false
        onTriggered: statusLabel.text = appController.connectionStatus
    }

    // Error popup for failed operations
    Dialog {
        id: errorDialog
        title: "Operation Failed"
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 400
        standardButtons: Dialog.Ok
        property alias text: errorLabel.text

        Label {
            id: errorLabel
            wrapMode: Text.WordWrap
            width: parent.width
            color: "#e53935"
        }
    }

    SetupDialog {
        id: setupDialog
    }

    ReplenishmentSettingsDialog {
        id: replSettingsDialog
    }

    Component.onCompleted: {
        if (appController.setupNeeded) {
            setupDialog.firstRun = true
            setupDialog.open()
        }
    }
}
