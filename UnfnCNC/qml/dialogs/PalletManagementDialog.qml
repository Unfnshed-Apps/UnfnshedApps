import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    title: "Pallet Management"
    width: 440
    anchors.centerIn: parent
    modal: true
    standardButtons: Dialog.NoButton

    property bool darkMode: {
        let bg = palette.window
        let luminance = (0.299 * bg.r + 0.587 * bg.g + 0.114 * bg.b)
        return luminance < 0.5
    }

    property color subtleText: darkMode ? "#999" : "#666"
    property color separatorColor: darkMode ? "#444" : "#ccc"

    onOpened: {
        cuttingController.refreshPalletInfo()
        m1Field.text = "0.7087"
        m2Field.text = "0.7087"
        m3Field.text = "0.7087"
        sheetCountSpinBox.value = 40
    }

    function computeAverage() {
        var v1 = parseFloat(m1Field.text) || 0
        var v2 = parseFloat(m2Field.text) || 0
        var v3 = parseFloat(m3Field.text) || 0
        return ((v1 + v2 + v3) / 3).toFixed(4)
    }

    contentItem: ColumnLayout {
        spacing: 10

        // ==================== Current Pallet Info ====================
        Label {
            text: "Current Pallet"
            font.bold: true
            font.pixelSize: 14
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: palletInfoCol.implicitHeight + 20
            radius: 6
            color: cuttingController.hasPallet
                ? (root.darkMode ? "#1a4ade80" : "#1a22c55e")
                : (root.darkMode ? "#1aff6b6b" : "#1aef4444")
            border.color: cuttingController.hasPallet
                ? (root.darkMode ? "#4ade80" : "#22c55e")
                : (root.darkMode ? "#ff6b6b" : "#ef4444")
            border.width: 1

            ColumnLayout {
                id: palletInfoCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 4

                Label {
                    text: cuttingController.hasPallet
                        ? "Pallet #" + cuttingController.palletId
                        : "No active pallet"
                    font.bold: true
                }

                Label {
                    visible: cuttingController.hasPallet
                    text: "Avg Thickness: " + cuttingController.palletThickness.toFixed(4) + "\""
                }

                Label {
                    visible: cuttingController.hasPallet
                    text: "Sheets Remaining: " + cuttingController.palletSheetsRemaining
                    color: cuttingController.palletSheetsRemaining <= 5
                        ? "#ef4444" : palette.windowText
                    font.bold: cuttingController.palletSheetsRemaining <= 5
                }

                RowLayout {
                    visible: cuttingController.hasPallet
                    spacing: 8
                    Layout.topMargin: 4

                    Button {
                        text: "Deplete Pallet"
                        palette.button: "#ef4444"
                        palette.buttonText: "white"
                        onClicked: depleteConfirmDialog.open()
                    }

                    Button {
                        text: "Refresh"
                        onClicked: cuttingController.refreshPalletInfo()
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: root.separatorColor
        }

        // ==================== Register New Pallet ====================
        Label {
            text: "Register New Pallet"
            font.bold: true
            font.pixelSize: 14
        }

        Label {
            text: cuttingController.hasPallet
                ? "Registering a new pallet will replace the current one."
                : "No pallet is currently assigned to this machine."
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            color: root.subtleText
            font.pixelSize: 11
        }

        Label {
            text: "Thickness Measurements (inches)"
            font.bold: true
        }

        GridLayout {
            columns: 2
            Layout.fillWidth: true
            columnSpacing: 8
            rowSpacing: 6

            Label { text: "Measurement 1:" }
            TextField {
                id: m1Field
                Layout.fillWidth: true
                text: "0.7087"
                validator: DoubleValidator { bottom: 0.5; top: 1.0; decimals: 4 }
                selectByMouse: true
                onTextChanged: avgLabel.text = "Average: " + root.computeAverage() + "\""
            }

            Label { text: "Measurement 2:" }
            TextField {
                id: m2Field
                Layout.fillWidth: true
                text: "0.7087"
                validator: DoubleValidator { bottom: 0.5; top: 1.0; decimals: 4 }
                selectByMouse: true
                onTextChanged: avgLabel.text = "Average: " + root.computeAverage() + "\""
            }

            Label { text: "Measurement 3:" }
            TextField {
                id: m3Field
                Layout.fillWidth: true
                text: "0.7087"
                validator: DoubleValidator { bottom: 0.5; top: 1.0; decimals: 4 }
                selectByMouse: true
                onTextChanged: avgLabel.text = "Average: " + root.computeAverage() + "\""
            }
        }

        Label {
            id: avgLabel
            text: "Average: 0.7087\""
            font.italic: true
            color: root.subtleText
        }

        RowLayout {
            spacing: 8

            Label {
                text: "Sheets on Pallet:"
                font.bold: true
            }
            SpinBox {
                id: sheetCountSpinBox
                from: 1
                to: 200
                value: 40
                editable: true
            }
        }

        // ==================== Buttons ====================
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 6
            spacing: 8

            Button {
                text: "Close"
                onClicked: root.close()
            }

            Item { Layout.fillWidth: true }

            Button {
                text: cuttingController.isBusy ? "Registering..." : "Register New Pallet"
                highlighted: true
                enabled: !cuttingController.isBusy
                onClicked: {
                    var v1 = parseFloat(m1Field.text) || 0.7087
                    var v2 = parseFloat(m2Field.text) || 0.7087
                    var v3 = parseFloat(m3Field.text) || 0.7087
                    var sheets = sheetCountSpinBox.value
                    cuttingController.registerNewPallet(v1, v2, v3, sheets)
                }
            }
        }
    }

    // Deplete confirmation sub-dialog
    Dialog {
        id: depleteConfirmDialog
        title: "Deplete Pallet"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Yes | Dialog.No

        Label {
            wrapMode: Text.WordWrap
            width: 350
            text: "Are you sure you want to mark Pallet #" +
                  cuttingController.palletId +
                  " as depleted?\n\nThis cannot be undone."
        }

        onAccepted: cuttingController.depletePallet()
    }
}
