import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: replDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 460
    title: "Replenishment Settings"
    standardButtons: Dialog.Ok | Dialog.Cancel

    property var configData: ({})

    onOpened: {
        inventoryController.loadReplenishmentConfig()
    }

    Connections {
        target: inventoryController
        function onReplenishmentConfigLoaded(cfg) {
            replDialog.configData = cfg
            minStockSpin.value = cfg.minimum_stock || 2
            reviewPeriodSpin.value = cfg.review_period_days || 7
            leadTimeSpin.value = cfg.lead_time_days || 3
            serviceZSpin.value = Math.round((cfg.service_z || 1.65) * 100)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        GroupBox {
            title: "Stock Levels"
            Layout.fillWidth: true

            GridLayout {
                columns: 2
                anchors.fill: parent
                columnSpacing: 8
                rowSpacing: 8

                Label { text: "Min Product Stock:" }
                SpinBox {
                    id: minStockSpin
                    from: 1
                    to: 50
                    value: 2
                    Layout.fillWidth: true
                }

                Label { text: "" }
                Label {
                    text: "Floor for all products, regardless of velocity."
                    font.pixelSize: 11
                    opacity: 0.6
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }

        GroupBox {
            title: "Replenishment Cycle"
            Layout.fillWidth: true

            GridLayout {
                columns: 2
                anchors.fill: parent
                columnSpacing: 8
                rowSpacing: 8

                Label { text: "Review Period (days):" }
                SpinBox {
                    id: reviewPeriodSpin
                    from: 1
                    to: 30
                    value: 7
                    Layout.fillWidth: true
                }

                Label { text: "Lead Time (days):" }
                SpinBox {
                    id: leadTimeSpin
                    from: 1
                    to: 14
                    value: 4
                    Layout.fillWidth: true
                }

                Label { text: "" }
                Label {
                    text: "Review = how often you nest.\nLead time = nesting to assembled product.\nTarget covers both periods."
                    font.pixelSize: 11
                    opacity: 0.6
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }

                Label { text: "Service Level:" }
                SpinBox {
                    id: serviceZSpin
                    from: 100
                    to: 300
                    value: 165
                    stepSize: 5
                    Layout.fillWidth: true

                    textFromValue: function(value, locale) {
                        return (value / 100).toFixed(2)
                    }
                    valueFromText: function(text, locale) {
                        return Math.round(parseFloat(text) * 100)
                    }
                }

                Label { text: "" }
                Label {
                    text: "Z-score for safety stock.\n1.28=90%, 1.65=95%, 1.96=97.5%"
                    font.pixelSize: 11
                    opacity: 0.6
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    onAccepted: {
        let updates = {
            "minimum_stock": minStockSpin.value,
            "review_period_days": reviewPeriodSpin.value,
            "lead_time_days": leadTimeSpin.value,
            "service_z": serviceZSpin.value / 100.0,
        }
        inventoryController.saveReplenishmentConfig(JSON.stringify(updates))
    }
}
