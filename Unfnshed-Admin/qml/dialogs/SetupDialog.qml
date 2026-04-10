import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: setupDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 420

    property bool firstRun: true

    title: firstRun ? "Unfnshed Admin Setup" : "Connection Settings"

    standardButtons: firstRun ? Dialog.Ok : (Dialog.Ok | Dialog.Cancel)

    onOpened: {
        if (firstRun) {
            deviceNameField.text = appController.suggestedDeviceName()
        } else {
            deviceNameField.text = appController.currentDeviceName()
            apiKeyField.text = appController.currentApiKey()
            apiUrlField.text = appController.currentApiUrl()
            lanIpField.text = appController.currentLanIp()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Label {
            visible: firstRun
            text: "Welcome to Unfnshed Admin"
            font.pixelSize: 16
            font.bold: true
        }

        Label {
            visible: firstRun
            text: "Enter a device name and your API key.\nThe server connection will be detected automatically."
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Rectangle {
            visible: firstRun
            Layout.fillWidth: true
            height: 1
            color: palette.mid
        }

        GroupBox {
            title: "Connection"
            Layout.fillWidth: true
            GridLayout {
                columns: 2
                anchors.fill: parent
                columnSpacing: 8
                rowSpacing: 8

                Label { text: "Device Name:" }
                TextField {
                    id: deviceNameField
                    Layout.fillWidth: true
                    placeholderText: "e.g., Admin-Station"
                }

                Label { text: "API Key:" }
                TextField {
                    id: apiKeyField
                    Layout.fillWidth: true
                    placeholderText: "Enter your server API key"
                    echoMode: showKeyCheck.checked ? TextInput.Normal : TextInput.Password
                }

                Label { text: "" }
                CheckBox {
                    id: showKeyCheck
                    text: "Show key"
                }
            }
        }

        GroupBox {
            visible: !firstRun
            title: "Advanced"
            Layout.fillWidth: true

            GridLayout {
                columns: 2
                anchors.fill: parent
                columnSpacing: 8
                rowSpacing: 8

                Label { text: "LAN Server IP:" }
                TextField {
                    id: lanIpField
                    Layout.fillWidth: true
                    placeholderText: "e.g., 192.168.0.242"
                }

                Label { text: "Server URL:" }
                TextField {
                    id: apiUrlField
                    Layout.fillWidth: true
                    placeholderText: "Leave blank for auto-detect"
                }
            }
        }

        RowLayout {
            spacing: 8
            Button {
                text: "Test Connection"
                onClicked: appController.testConnection()
            }
            Label {
                text: appController.testStatus
                color: appController.testStatusOk ? "green" : (appController.testStatus !== "" ? "red" : palette.windowText)
            }
        }
    }

    onAccepted: {
        let name = deviceNameField.text.trim()
        if (!name) return
        appController.saveSetupSettings(
            name,
            apiKeyField.text.trim(),
            apiUrlField.text.trim(),
            lanIpField.text.trim()
        )
    }
}
