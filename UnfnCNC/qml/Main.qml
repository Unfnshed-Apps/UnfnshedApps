import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import UnfnCNC 1.0
import "dialogs"

ApplicationWindow {
    id: root
    visible: true
    width: 900
    height: 650
    minimumWidth: 800
    minimumHeight: 550
    title: "UnfnCNC - " + appController.machineLetter

    property bool darkMode: {
        let bg = palette.window
        let luminance = (0.299 * bg.r + 0.587 * bg.g + 0.114 * bg.b)
        return luminance < 0.5
    }

    property string statusText: ""

    // ==================== Header ToolBar ====================
    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12

            ColumnLayout {
                spacing: 0
                Label {
                    text: "UnfnCNC - " + appController.machineLetter
                    font.pixelSize: 18
                    font.bold: true
                }
                Label {
                    text: cuttingController.zeroReference
                    font.pixelSize: 11
                    opacity: 0.6
                }
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "Load Prototype"
                visible: cuttingController.isIdle
                palette.button: "#d97706"
                palette.buttonText: root.darkMode ? "white" : "black"
                onClicked: cuttingController.loadPrototypeSheet()
            }

            Button {
                text: "Settings"
                onClicked: { setupDialog.firstRun = false; setupDialog.open() }
            }
        }
    }

    // ==================== Main Content ====================
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 10

        // Connection status
        Label {
            text: appController.connectionStatus
            color: "gray"
            font.pixelSize: 11
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: root.darkMode ? "#555" : "#ccc"
        }

        // SplitView: preview + info
        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            SheetPreview {
                SplitView.preferredWidth: 400
                SplitView.minimumWidth: 200
                darkMode: root.darkMode
            }

            SheetInfoPanel {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 200
            }
        }

        // Big action button
        Button {
            id: actionBtn
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            font.pixelSize: 16
            font.bold: true
            enabled: !cuttingController.isBusy

            text: {
                if (cuttingController.isBusy)
                    return cuttingController.busyText
                if (cuttingController.isIdle)
                    return "Load Next Sheet"
                if (cuttingController.isPrototype)
                    return "Cut Complete (Prototype)"
                return "Cut Complete"
            }

            palette.button: {
                if (cuttingController.isBusy) return "#9ca3af"
                if (cuttingController.isIdle) return "#3b82f6"
                if (cuttingController.isPrototype) return "#d97706"
                return "#22c55e"
            }
            palette.buttonText: root.darkMode ? "white" : "black"

            onClicked: {
                if (cuttingController.isIdle)
                    cuttingController.loadNextSheet()
                else if (cuttingController.isCutting)
                    cuttingController.cutComplete()
            }
        }

        // Status message
        Label {
            id: statusLabel
            text: root.statusText
            visible: root.statusText !== ""
            color: root.darkMode ? "#aaa" : "#666"
            font.pixelSize: 11
        }

        // Footer: queue + completed
        RowLayout {
            Layout.fillWidth: true

            Label {
                Layout.preferredWidth: 250
                text: cuttingController.queueText
                font.pixelSize: 12
            }
            Item { Layout.fillWidth: true }
            Label {
                Layout.preferredWidth: 250
                text: cuttingController.completedText
                font.pixelSize: 12
                horizontalAlignment: Text.AlignRight
            }
        }
    }

    // ==================== Signal Connections ====================

    Connections {
        target: cuttingController
        function onStatusMessage(msg, timeout) {
            root.statusText = msg
            statusResetTimer.interval = timeout
            statusResetTimer.restart()
        }
        function onOperationFailed(msg) {
            errorDialog.text = msg
            errorDialog.open()
        }
        function onDamageCheckRequested() {
            damageConfirmDialog.open()
        }
        function onThicknessNeeded() {
            thicknessDialog.open()
        }
        function onOrphanDetected(jobName, sheetText, jobId, sheetId) {
            orphanDialog.jobName = jobName
            orphanDialog.sheetText = sheetText
            orphanDialog.jobId = jobId
            orphanDialog.sheetId = sheetId
            orphanDialog.open()
        }
    }

    Connections {
        target: appController
        function onStatusMessage(msg, timeout) {
            root.statusText = msg
            statusResetTimer.interval = timeout
            statusResetTimer.restart()
        }
    }

    Timer {
        id: statusResetTimer
        interval: 5000
        onTriggered: root.statusText = ""
    }

    // ==================== Dialogs ====================

    // Error dialog
    Dialog {
        id: errorDialog
        title: "Error"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Ok

        property string text: ""

        Label {
            text: errorDialog.text
            wrapMode: Text.WordWrap
            width: 400
        }
    }

    // Damage confirmation: "Were any parts damaged?"
    Dialog {
        id: damageConfirmDialog
        title: "Cut Complete"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Yes | Dialog.No | Dialog.Cancel

        Label {
            text: "Were any parts damaged or lost?"
        }

        onAccepted: {
            // "Yes" — open damage dialog
            cuttingController.prepareDamageData()
            damagedPartsDialog.open()
        }
        onRejected: {
            // "No" — mark cut with no damage
            cuttingController.cutCompleteNoDamage()
        }
        // Cancel button handler
        Component.onCompleted: {
            // The Dialog handles Cancel by closing without accepted/rejected
        }
    }

    // Orphan detection dialog
    Dialog {
        id: orphanDialog
        title: "Orphaned Sheet Detected"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Yes | Dialog.No

        property string jobName: ""
        property string sheetText: ""
        property int jobId: 0
        property int sheetId: 0

        Label {
            wrapMode: Text.WordWrap
            width: 400
            text: appController.machineLetter + " has a sheet still claimed " +
                  "from a previous session:\n\n" +
                  "  " + orphanDialog.jobName + " — " + orphanDialog.sheetText + "\n\n" +
                  "This was likely caused by a crash or unexpected close.\n" +
                  "Would you like to release it back to the queue?"
        }

        onAccepted: cuttingController.releaseOrphan(orphanDialog.jobId, orphanDialog.sheetId)
    }

    // Release confirmation dialog
    Dialog {
        id: releaseConfirmDialog
        title: "Release Sheet"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Yes | Dialog.No

        Label {
            wrapMode: Text.WordWrap
            width: 400
            text: "Release this sheet back to the queue?\nThe G-code file will be removed from the hot folder."
        }

        onAccepted: cuttingController.releaseSheet()
    }

    // Damaged parts dialog
    DamagedPartsDialog {
        id: damagedPartsDialog
    }

    // Thickness dialog (shown during sheet load)
    ThicknessDialog {
        id: thicknessDialog
    }

    // Setup / settings dialog (QML replacement for QWidgets SetupDialog)
    SetupDialog {
        id: setupDialog
    }

    // First-run check: show setup dialog if not configured
    Component.onCompleted: {
        if (settingsController.setupNeeded) {
            setupDialog.firstRun = true
            setupDialog.open()
        }
    }
}
