import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../dialogs"

Item {
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 4

        // Header
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Select products and quantities:" }
            Item { Layout.fillWidth: true }
            Button {
                text: "+ Add Product"
                onClicked: productDialog.openForAdd()
            }
            Button {
                text: "Edit"
                onClicked: {
                    if (productList.currentIndex >= 0) {
                        let sku = productController.skuAtRow(productList.currentIndex)
                        productDialog.openForEdit(sku)
                    }
                }
            }
            Button {
                text: "Delete"
                onClicked: {
                    if (productList.currentIndex >= 0)
                        deleteConfirmDialog.open()
                }
            }
        }

        // List
        ListView {
            id: productList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: productController.model
            currentIndex: -1

            header: Rectangle {
                width: productList.width
                height: 30
                color: root.darkMode ? "#3a3a3a" : "#e8e8e8"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 14
                    spacing: 4
                    Label { text: "SKU"; Layout.preferredWidth: 100; font.bold: true }
                    Label { text: "Name"; Layout.fillWidth: true; font.bold: true }
                    Label { text: "Quantity"; Layout.preferredWidth: 120; font.bold: true }
                }
            }

            delegate: Rectangle {
                width: productList.width
                height: 40
                color: productList.currentIndex === index
                    ? (root.darkMode ? "#4a5568" : "#cce5ff")
                    : (index % 2 === 0
                        ? (root.darkMode ? "#2d2d2d" : "#ffffff")
                        : (root.darkMode ? "#333333" : "#f8f8f8"))

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        productList.currentIndex = index
                        forceActiveFocus()
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 14
                    spacing: 4

                    Label {
                        text: model.sku
                        Layout.preferredWidth: 100
                        elide: Text.ElideRight
                    }
                    Label {
                        text: model.name
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    SpinBox {
                        id: qtySpinBox
                        Layout.preferredWidth: 120
                        from: 0
                        to: 9999
                        editable: true
                        value: model.quantity
                        onValueModified: productController.setQuantity(index, value)
                        onActiveFocusChanged: {
                            if (activeFocus) {
                                contentItem.forceActiveFocus()
                            }
                        }
                        // Select row when clicking SpinBox area
                        MouseArea {
                            anchors.fill: parent
                            z: 100
                            onPressed: function(mouse) {
                                productList.currentIndex = index
                                mouse.accepted = false
                            }
                        }
                    }
                    Connections {
                        target: qtySpinBox.contentItem
                        function onTextChanged() {
                            if (qtySpinBox.activeFocus) {
                                var newVal = parseInt(qtySpinBox.contentItem.text)
                                if (!isNaN(newVal) && newVal >= qtySpinBox.from && newVal <= qtySpinBox.to) {
                                    productController.setQuantity(index, newVal)
                                }
                            }
                        }
                        function onAccepted() {
                            qtySpinBox.value = qtySpinBox.valueFromText(qtySpinBox.contentItem.text, Qt.locale())
                            productController.setQuantity(index, qtySpinBox.value)
                            qtySpinBox.focus = false
                        }
                        function onActiveFocusChanged() {
                            if (!qtySpinBox.contentItem.activeFocus) {
                                qtySpinBox.value = qtySpinBox.valueFromText(qtySpinBox.contentItem.text, Qt.locale())
                                productController.setQuantity(index, qtySpinBox.value)
                            }
                        }
                    }
                }
            }

            ScrollBar.vertical: ScrollBar {}
        }

        // Delete confirmation
        Dialog {
            id: deleteConfirmDialog
            title: "Confirm Delete"
            modal: true
            anchors.centerIn: Overlay.overlay
            standardButtons: Dialog.Yes | Dialog.No

            Label {
                text: productList.currentIndex >= 0
                    ? "Are you sure you want to delete product '" + productController.skuAtRow(productList.currentIndex) + "'?\n\nThis cannot be undone."
                    : ""
                wrapMode: Text.WordWrap
            }

            onAccepted: productController.deleteProduct(productList.currentIndex)
        }
    }

    // Product dialog (Add/Edit)
    ProductDialog {
        id: productDialog
    }
}
