import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: replDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 400
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
                    text: "Minimum desired stock per product.\nTarget = max(velocity x 7 days, minimum)."
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
        }
        inventoryController.saveReplenishmentConfig(JSON.stringify(updates))
    }
}
