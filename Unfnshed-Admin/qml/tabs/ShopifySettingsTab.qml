import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../dialogs"

Item {
    id: shopifyTab

    ScrollView {
        anchors.fill: parent
        clip: true

    ColumnLayout {
        width: shopifyTab.width - 16
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
                    // Write-only: never bound to a controller value so the
                    // stored secret can't be round-tripped back on save.
                    placeholderText: shopifyController.clientSecretStored
                        ? "Stored: " + shopifyController.clientSecretMasked + " — type to replace"
                        : "From Dev Dashboard > App > Settings"
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

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                // Use Live Key toggle. Bound two-way to the controller's
                // shippoUseLive property; the confirmation dialog is wired
                // separately on the explicit toggle action so that going
                // from test → live always requires the user's confirmation.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Label {
                        text: "Use Live Key"
                        Layout.alignment: Qt.AlignVCenter
                    }
                    Switch {
                        id: useLiveSwitch
                        checked: shopifyController.shippoUseLive
                        Layout.alignment: Qt.AlignVCenter
                        onClicked: {
                            // Going from test → live: require explicit confirm.
                            // Going from live → test: silent (downgrading
                            // safety needs no confirmation).
                            if (checked && !shopifyController.shippoUseLive) {
                                checked = false  // revert until confirmed
                                liveModeConfirmDialog.open()
                            } else {
                                shopifyController.shippoUseLive = checked
                            }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        text: shopifyController.shippoUseLive ? "LIVE MODE" : "TEST MODE"
                        font.bold: true
                        color: shopifyController.shippoUseLive ? "#D32F2F" : "#388E3C"
                        Layout.alignment: Qt.AlignVCenter
                    }
                }

                GridLayout {
                    columns: 2
                    columnSpacing: 12
                    rowSpacing: 8
                    Layout.fillWidth: true

                    Label { text: "Test API Key:" }
                    TextField {
                        id: shippoTestKeyField
                        // Write-only: never bound to a controller value so
                        // the stored key can't be round-tripped back on save.
                        placeholderText: shopifyController.shippoTestKeyStored
                            ? "Stored: " + shopifyController.shippoTestKeyMasked + " — type to replace"
                            : "Starts with shippo_test_..."
                        echoMode: TextInput.Password
                        Layout.fillWidth: true
                    }

                    Label { text: "Live API Key:" }
                    TextField {
                        id: shippoLiveKeyField
                        placeholderText: shopifyController.shippoLiveKeyStored
                            ? "Stored: " + shopifyController.shippoLiveKeyMasked + " — type to replace"
                            : "Starts with shippo_live_..."
                        echoMode: TextInput.Password
                        Layout.fillWidth: true
                    }
                }

                Label {
                    text: "Test labels are mock — no charge.\nLive labels charge real money and modify real inventory when fulfilled."
                    font.pixelSize: 11
                    color: palette.placeholderText
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
            }
        }

        // Confirmation dialog when toggling test → live. The Switch is
        // reverted before this opens; on accept we set the controller
        // property and re-sync the Switch state.
        Dialog {
            id: liveModeConfirmDialog
            modal: true
            anchors.centerIn: Overlay.overlay
            title: "Switch to LIVE mode?"
            standardButtons: Dialog.Yes | Dialog.No

            Label {
                text: "Live mode will charge your Shippo account when labels " +
                      "are purchased and will modify real inventory when " +
                      "orders are fulfilled.\n\nAre you sure?"
                wrapMode: Text.WordWrap
                width: 360
            }

            onAccepted: {
                shopifyController.shippoUseLive = true
                useLiveSwitch.checked = true
            }
            onRejected: {
                useLiveSwitch.checked = false
            }
        }

        // ── Ship-From Address ──────────────────────────────
        GroupBox {
            title: "Ship-From Address"
            Layout.fillWidth: true

            GridLayout {
                anchors.fill: parent
                columns: 2
                columnSpacing: 12
                rowSpacing: 8

                Label { text: "Name:" }
                TextField {
                    id: shipFromName
                    placeholderText: "Business name"
                    text: shopifyController.shipFrom.name || ""
                    Layout.fillWidth: true
                }

                Label { text: "Street 1:" }
                TextField {
                    id: shipFromStreet1
                    placeholderText: "Street address"
                    text: shopifyController.shipFrom.street1 || ""
                    Layout.fillWidth: true
                }

                Label { text: "Street 2:" }
                TextField {
                    id: shipFromStreet2
                    placeholderText: "Apt, suite, etc. (optional)"
                    text: shopifyController.shipFrom.street2 || ""
                    Layout.fillWidth: true
                }

                Label { text: "City:" }
                TextField {
                    id: shipFromCity
                    text: shopifyController.shipFrom.city || ""
                    Layout.fillWidth: true
                }

                Label { text: "State:" }
                TextField {
                    id: shipFromState
                    placeholderText: "e.g. NY"
                    text: shopifyController.shipFrom.state || ""
                    Layout.fillWidth: true
                }

                Label { text: "ZIP:" }
                TextField {
                    id: shipFromZip
                    text: shopifyController.shipFrom.zip || ""
                    Layout.fillWidth: true
                }

                Label { text: "Country:" }
                TextField {
                    id: shipFromCountry
                    placeholderText: "US"
                    text: shopifyController.shipFrom.country || "US"
                    Layout.fillWidth: true
                }

                Label { text: "Phone:" }
                TextField {
                    id: shipFromPhone
                    placeholderText: "Required for some carriers"
                    text: shopifyController.shipFrom.phone || ""
                    Layout.fillWidth: true
                }

                Label { text: "Email:" }
                TextField {
                    id: shipFromEmail
                    placeholderText: "Required by Shippo for labels"
                    text: shopifyController.shipFrom.email || ""
                    Layout.fillWidth: true
                }
            }
        }

        RowLayout {
            spacing: 8
            Button {
                text: "Save Ship-From"
                onClicked: shopifyController.saveShipFrom({
                    "name": shipFromName.text,
                    "street1": shipFromStreet1.text,
                    "street2": shipFromStreet2.text,
                    "city": shipFromCity.text,
                    "state": shipFromState.text,
                    "zip": shipFromZip.text,
                    "country": shipFromCountry.text,
                    "phone": shipFromPhone.text,
                    "email": shipFromEmail.text,
                })
            }
            Item { Layout.fillWidth: true }
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
                    shippoTestKeyField.text,
                    shippoLiveKeyField.text
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
    }

    // ── Confirm Clear Dialog ───────────────────────────────
    ConfirmDialog {
        id: clearConfirmDialog
        title: "Confirm Clear"
        message: "Are you sure you want to clear all Shopify settings?\n\nThis will disconnect from Shopify."
        onAccepted: shopifyController.clearSettings()
    }

    // Update fields when settings are reloaded externally.
    // Secret fields are deliberately NOT reset here — they are write-only
    // inputs that only ever hold what the user is currently typing.
    Connections {
        target: shopifyController
        function onStoreUrlChanged() { storeUrlField.text = shopifyController.storeUrl }
        function onClientIdChanged() { clientIdField.text = shopifyController.clientId }
        function onSettingsSaved() {
            // Clear all secret inputs after a successful save so the stored
            // placeholder takes over for the next visit. Both Shippo key
            // fields are cleared so the user sees the freshly-stored mask
            // on the next render.
            clientSecretField.text = ""
            shippoTestKeyField.text = ""
            shippoLiveKeyField.text = ""
        }
        function onShipFromChanged() {
            shipFromName.text = shopifyController.shipFrom.name || ""
            shipFromStreet1.text = shopifyController.shipFrom.street1 || ""
            shipFromStreet2.text = shopifyController.shipFrom.street2 || ""
            shipFromCity.text = shopifyController.shipFrom.city || ""
            shipFromState.text = shopifyController.shipFrom.state || ""
            shipFromZip.text = shopifyController.shipFrom.zip || ""
            shipFromCountry.text = shopifyController.shipFrom.country || "US"
            shipFromPhone.text = shopifyController.shipFrom.phone || ""
            shipFromEmail.text = shopifyController.shipFrom.email || ""
        }
        function onApiVersionChanged() {
            var idx = apiVersionCombo.find(shopifyController.apiVersion)
            if (idx >= 0) apiVersionCombo.currentIndex = idx
        }
    }
}
