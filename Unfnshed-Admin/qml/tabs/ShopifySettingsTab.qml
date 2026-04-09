import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../dialogs"

Item {
    id: shopifyTab

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 16

        // ── Connection Status ──────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            height: 40
            radius: 4
            color: palette.alternateBase
            border.color: palette.mid
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8

                Rectangle {
                    width: 12; height: 12; radius: 6
                    color: shopifyController.statusOk ? "#4CAF50" : "#888888"
                }

                Label {
                    text: shopifyController.statusText
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }

        // ── Credentials Form ───────────────────────────────
        GroupBox {
            title: "Shopify Credentials"
            Layout.fillWidth: true

            GridLayout {
                anchors.fill: parent
                columns: 2
                columnSpacing: 12
                rowSpacing: 8

                Label { text: "Store URL:" }
                TextField {
                    id: storeUrlField
                    placeholderText: "your-store.myshopify.com"
                    text: shopifyController.storeUrl
                    Layout.fillWidth: true
                }

                Label { text: "Client ID:" }
                TextField {
                    id: clientIdField
                    placeholderText: "From Dev Dashboard > App > Settings"
                    text: shopifyController.clientId
                    Layout.fillWidth: true
                }

                Label { text: "Client Secret:" }
                TextField {
                    id: clientSecretField
                    placeholderText: "From Dev Dashboard > App > Settings"
                    text: shopifyController.clientSecret
                    echoMode: TextInput.Password
                    Layout.fillWidth: true
                }

                Label { text: "API Version:" }
                ComboBox {
                    id: apiVersionCombo
                    model: shopifyController.apiVersionOptions
                    Layout.fillWidth: true
                    Component.onCompleted: {
                        var idx = find(shopifyController.apiVersion)
                        if (idx >= 0) currentIndex = idx
                    }
                }
            }
        }

        // ── Shippo Credentials ─────────────────────────────
        GroupBox {
            title: "Shippo (Shipping)"
            Layout.fillWidth: true

            GridLayout {
                anchors.fill: parent
                columns: 2
                columnSpacing: 12
                rowSpacing: 8

                Label { text: "API Key:" }
                TextField {
                    id: shippoKeyField
                    placeholderText: "Enter Shippo API key (test or live)"
                    text: shopifyController.shippoApiKey
                    echoMode: TextInput.Password
                    Layout.fillWidth: true
                }

                Label { text: "" }
                Label {
                    text: "From goshippo.com > Settings > API.\nUse a test key for development."
                    font.pixelSize: 11
                    color: palette.placeholderText
                }
            }
        }

        // ── Buttons ────────────────────────────────────────
        RowLayout {
            spacing: 8

            Button {
                text: "Test Connection"
                onClicked: shopifyController.testConnection(
                    storeUrlField.text,
                    clientIdField.text,
                    clientSecretField.text,
                    apiVersionCombo.currentText
                )
            }

            Button {
                text: "Save Settings"
                highlighted: true
                onClicked: shopifyController.saveSettings(
                    storeUrlField.text,
                    clientIdField.text,
                    clientSecretField.text,
                    apiVersionCombo.currentText,
                    shippoKeyField.text
                )
            }

            Button {
                text: "Clear Settings"
                onClicked: clearConfirmDialog.open()

                palette.button: "#f44336"
                palette.buttonText: "white"
            }

            Item { Layout.fillWidth: true }
        }

        // ── Help Text ──────────────────────────────────────
        Label {
            text: "To get credentials:\n" +
                  "1. Go to Shopify Dev Dashboard > Your App > Settings\n" +
                  "2. Copy Client ID and Client Secret\n" +
                  "3. Make sure the app is installed on your store"
            color: palette.placeholderText
            font.pixelSize: 11
        }

        Item { Layout.fillHeight: true }
    }

    // ── Confirm Clear Dialog ───────────────────────────────
    ConfirmDialog {
        id: clearConfirmDialog
        title: "Confirm Clear"
        message: "Are you sure you want to clear all Shopify settings?\n\nThis will disconnect from Shopify."
        onAccepted: shopifyController.clearSettings()
    }

    // Update fields when settings are reloaded externally
    Connections {
        target: shopifyController
        function onStoreUrlChanged() { storeUrlField.text = shopifyController.storeUrl }
        function onClientIdChanged() { clientIdField.text = shopifyController.clientId }
        function onClientSecretChanged() { clientSecretField.text = shopifyController.clientSecret }
        function onShippoApiKeyChanged() { shippoKeyField.text = shopifyController.shippoApiKey }
        function onApiVersionChanged() {
            var idx = apiVersionCombo.find(shopifyController.apiVersion)
            if (idx >= 0) apiVersionCombo.currentIndex = idx
        }
    }
}
