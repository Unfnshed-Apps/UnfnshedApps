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
        shippoKeyField.text = appController.getConfigValue("shippo_api_key")

        // Load available printers
        printerList = appController.getAvailablePrinters()
        printerCombo.model = printerList

        // Select current printer
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

        GroupBox {
            title: "Shippo"
            Layout.fillWidth: true

            GridLayout {
                columns: 2
                anchors.fill: parent
                columnSpacing: 8
                rowSpacing: 8

                Label { text: "API Key:" }
                TextField {
                    id: shippoKeyField
                    Layout.fillWidth: true
                    placeholderText: "Enter Shippo API key"
                    echoMode: showKeyCheck.checked ? TextInput.Normal : TextInput.Password
                }

                Label { text: "" }
                CheckBox {
                    id: showKeyCheck
                    text: "Show key"
                }

                Label { text: "" }
                Label {
                    text: "Get your API key from goshippo.com/settings/api"
                    font.pixelSize: 11
                    opacity: 0.6
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    onAccepted: {
        appController.setConfigValue("shippo_api_key", shippoKeyField.text.trim())
        if (printerCombo.currentIndex >= 0) {
            appController.setConfigValue("label_printer", printerList[printerCombo.currentIndex])
        }
    }
}
