import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "dialogs"

ApplicationWindow {
    id: root
    title: "Unfnship"
    width: 950
    height: 600
    minimumWidth: 800
    minimumHeight: 500
    visible: true

    menuBar: MenuBar {
        Menu {
            title: "File"
            Action {
                text: "Settings..."
                onTriggered: { setupDialog.firstRun = false; setupDialog.open() }
            }
            Action {
                text: "Shipping Settings..."
                onTriggered: shippingSettingsDialog.open()
            }
            MenuSeparator {}
            Action {
                text: "Quit"
                onTriggered: Qt.quit()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // TEST MODE banner — visible whenever the server's active Shippo
        // key is a test key. Bright orange so it's impossible to miss.
        // Truthful copy: in test mode, Shippo labels are mock and any
        // future inventory mutations will be skipped server-side.
        Rectangle {
            Layout.fillWidth: true
            visible: shippingController.testMode
            color: "#F57C00"
            implicitHeight: testModeLabel.implicitHeight + 12

            Label {
                id: testModeLabel
                anchors.centerIn: parent
                text: "TEST MODE — Shippo labels are mock, inventory and Shopify are untouched"
                color: "white"
                font.bold: true
                font.pixelSize: 13
            }
        }

        // Toolbar
        ToolBar {
            Layout.fillWidth: true
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8

                Label {
                    text: "Shipping Queue"
                    font.pixelSize: 16
                    font.bold: true
                }

                Item { Layout.fillWidth: true }

                Button {
                    text: "Refresh"
                    onClicked: shippingController.refresh()
                }
            }
        }

        // Split: queue on left, detail on right
        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            OrderQueue {
                SplitView.preferredWidth: parent.width * 0.6
                SplitView.minimumWidth: 400
            }

            OrderDetail {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 350
            }
        }
    }

    // Status bar
    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8

            Label {
                id: connectionLabel
                text: appController.connectionStatus
                color: appController.connectionOk ? palette.windowText : "#e53935"
            }

            Item { Layout.fillWidth: true }

            Label {
                id: statusLabel
                text: ""
                color: palette.placeholderText
            }
        }
    }

    // Status message handling
    Timer {
        id: statusTimer
        interval: 3000
        onTriggered: statusLabel.text = ""
    }

    Connections {
        target: appController
        function onStatusMessage(msg, timeout) {
            statusLabel.text = msg
            if (timeout > 0) { statusTimer.interval = timeout; statusTimer.start() }
        }
    }

    Connections {
        target: shippingController
        function onStatusMessage(msg, timeout) {
            statusLabel.text = msg
            if (timeout > 0) { statusTimer.interval = timeout; statusTimer.start() }
        }
        function onOperationFailed(msg) {
            errorDialog.text = msg
            errorDialog.open()
        }
    }

    // Error dialog
    Dialog {
        id: errorDialog
        property string text: ""
        modal: true
        anchors.centerIn: Overlay.overlay
        title: "Error"
        standardButtons: Dialog.Ok
        Label {
            text: errorDialog.text
            wrapMode: Text.WordWrap
        }
    }

    // Dialogs
    SetupDialog {
        id: setupDialog
    }

    ShippingSettingsDialog {
        id: shippingSettingsDialog
    }

    Component.onCompleted: {
        if (appController.setupNeeded) {
            setupDialog.firstRun = true
            setupDialog.open()
        }
    }
}
