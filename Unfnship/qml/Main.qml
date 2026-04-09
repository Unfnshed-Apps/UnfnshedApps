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

        // Order queue
        OrderQueue {
            Layout.fillWidth: true
            Layout.fillHeight: true
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
