import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: productAdjustDialog
    title: "Adjust: " + productName
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 380
    standardButtons: Dialog.Ok | Dialog.Cancel

    property string productSku: ""
    property string productName: ""
    property int currentStock: 0

    onOpened: {
        qtySpin.value = 0
        reasonCombo.currentIndex = 0
        notesField.text = ""
    }

    onAccepted: {
        if (qtySpin.value === 0)
            return
        productInventoryController.adjustInventory(
            productSku,
            qtySpin.value,
            reasonCombo.currentText,
            notesField.text
        )
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        // Current quantity
        Label {
            text: "Current quantity: " + currentStock
            font.bold: true
        }

        // Adjustment spinbox
        GridLayout {
            columns: 2
            columnSpacing: 12
            rowSpacing: 8
            Layout.fillWidth: true

            Label { text: "Adjustment (+/-):" }
            SpinBox {
                id: qtySpin
                from: -9999
                to: 9999
                value: 0
                editable: true
                Layout.fillWidth: true
            }

            Label { text: "Reason:" }
            ComboBox {
                id: reasonCombo
                model: ["adjustment", "damaged", "correction", "inventory_count"]
                Layout.fillWidth: true
            }

            Label { text: "Notes:" }
            TextField {
                id: notesField
                placeholderText: "Optional notes..."
                Layout.fillWidth: true
            }
        }

        // Result preview
        Label {
            id: resultLabel
            text: "New quantity: " + (currentStock + qtySpin.value)
            font.bold: true
            color: qtySpin.value > 0 ? "#4caf50"
                 : qtySpin.value < 0 ? "#e53935"
                 : palette.placeholderText
        }
    }
}
