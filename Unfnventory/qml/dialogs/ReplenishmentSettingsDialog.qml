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
            targetDaysASpin.value = cfg.target_days_a || 4
            targetDaysBSpin.value = cfg.target_days_b || 2
            reorderDaysASpin.value = cfg.reorder_days_a || 2
            reorderDaysBSpin.value = cfg.reorder_days_b || 1
            toleranceSpin.value = Math.round((cfg.tolerance_ceiling || 1.25) * 100)
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
                    text: "Minimum desired stock per product.\nComponent minimums are derived via BOM."
                    font.pixelSize: 11
                    opacity: 0.6
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }

                Label { text: "Overage Tolerance:" }
                SpinBox {
                    id: toleranceSpin
                    from: 100
                    to: 200
                    value: 125
                    stepSize: 5
                    Layout.fillWidth: true

                    property int decimals: 2
                    textFromValue: function(value, locale) {
                        return (value / 100).toFixed(2) + "x"
                    }
                    valueFromText: function(text, locale) {
                        return Math.round(parseFloat(text) * 100)
                    }
                }

                Label { text: "" }
                Label {
                    text: "Fill candidates below target x tolerance"
                    font.pixelSize: 11
                    opacity: 0.6
                }
            }
        }

        GroupBox {
            title: "Target Days of Supply"
            Layout.fillWidth: true

            GridLayout {
                columns: 2
                anchors.fill: parent
                columnSpacing: 8
                rowSpacing: 8

                Label { text: "A-class target days:" }
                SpinBox {
                    id: targetDaysASpin
                    from: 1
                    to: 14
                    value: 4
                    Layout.fillWidth: true
                }

                Label { text: "B/C-class target days:" }
                SpinBox {
                    id: targetDaysBSpin
                    from: 1
                    to: 14
                    value: 2
                    Layout.fillWidth: true
                }

                Label { text: "A-class reorder days:" }
                SpinBox {
                    id: reorderDaysASpin
                    from: 1
                    to: 14
                    value: 2
                    Layout.fillWidth: true
                }

                Label { text: "B/C-class reorder days:" }
                SpinBox {
                    id: reorderDaysBSpin
                    from: 1
                    to: 14
                    value: 1
                    Layout.fillWidth: true
                }
            }
        }
    }

    onAccepted: {
        let updates = {
            "minimum_stock": minStockSpin.value,
            "target_days_a": targetDaysASpin.value,
            "target_days_b": targetDaysBSpin.value,
            "reorder_days_a": reorderDaysASpin.value,
            "reorder_days_b": reorderDaysBSpin.value,
            "tolerance_ceiling": toleranceSpin.value / 100.0,
        }
        inventoryController.saveReplenishmentConfig(JSON.stringify(updates))
    }
}
