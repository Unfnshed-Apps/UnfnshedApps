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

    onOpened: {
        shippoKeyField.text = appController.getConfigValue("shippo_api_key")
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

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
    }
}
