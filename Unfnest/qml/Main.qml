import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "dialogs"

ApplicationWindow {
    id: root
    title: "Unfnest"
    width: 1200
    height: 800
    minimumWidth: 900
    minimumHeight: 600
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
                text: "API Settings..."
                onTriggered: { setupDialog.firstRun = false; setupDialog.open() }
            }
            MenuSeparator {}
            Action {
                text: "Exit"
                onTriggered: Qt.quit()
            }
        }
    }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        LeftPanel {
            id: leftPanel
            SplitView.fillWidth: true
            SplitView.minimumWidth: 300
        }

        RightPanel {
            id: rightPanel
            SplitView.preferredWidth: 480
            SplitView.minimumWidth: 300
        }
    }

    // Click anywhere to dismiss focus from text inputs (after SplitView for z-order)
    MouseArea {
        anchors.fill: parent
        onPressed: function(mouse) {
            root.contentItem.forceActiveFocus()
            mouse.accepted = false
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

            ProgressBar {
                id: progressBar
                visible: nestingController.isRunning
                from: 0
                to: nestingController.progressTotal
                value: nestingController.progressCurrent
                Layout.preferredWidth: 200
            }
        }
    }

    // Shared handler for status messages from any controller
    function showStatus(msg, timeout) {
        statusLabel.text = msg
        if (timeout > 0) {
            statusTimer.interval = timeout
            statusTimer.start()
        }
    }

    function showError(msg) {
        errorDialog.text = msg
        errorDialog.open()
    }

    Connections {
        target: appController
        function onStatusMessage(msg, timeout) { root.showStatus(msg, timeout) }
    }
    Connections {
        target: nestingController
        function onStatusMessage(msg, timeout) { root.showStatus(msg, timeout) }
    }
    Connections {
        target: componentController
        function onStatusMessage(msg, timeout) { root.showStatus(msg, timeout) }
        function onOperationFailed(msg) { root.showError(msg) }
    }
    Connections {
        target: productController
        function onStatusMessage(msg, timeout) { root.showStatus(msg, timeout) }
        function onOperationFailed(msg) { root.showError(msg) }
    }
    Connections {
        target: replenishmentController
        function onStatusMessage(msg, timeout) { root.showStatus(msg, timeout) }
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

    // Setup / API settings dialog
    SetupDialog {
        id: setupDialog
    }

    Component.onCompleted: {
        if (appController.setupNeeded) {
            setupDialog.firstRun = true
            setupDialog.open()
        }
    }
}
