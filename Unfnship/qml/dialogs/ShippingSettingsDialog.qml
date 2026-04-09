import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: shippingSettingsDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 420
    title: "Shipping Settings"
    standardButtons: Dialog.Ok | Dialog.Cancel

    property var printerList: []

    onOpened: {
        printerList = appController.getAvailablePrinters()
        printerCombo.model = printerList

        let current = appController.getConfigValue("label_printer")
        let idx = printerList.indexOf(current)
        printerCombo.currentIndex = idx >= 0 ? idx : -1
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        GroupBox {
            title: "Label Printer"
            Layout.fillWidth: true

            GridLayout {
                columns: 2
                anchors.fill: parent
                columnSpacing: 8
                rowSpacing: 8

                Label { text: "Printer:" }
                ComboBox {
                    id: printerCombo
                    Layout.fillWidth: true
                    model: []
                }

                Label { text: "" }
                Label {
                    text: "Select the label printer for this station.\nLabels print automatically with no dialog."
                    font.pixelSize: 11
                    opacity: 0.6
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    onAccepted: {
        if (printerCombo.currentIndex >= 0) {
            appController.setConfigValue("label_printer", printerList[printerCombo.currentIndex])
        }
    }
}
