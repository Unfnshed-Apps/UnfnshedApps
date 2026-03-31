import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Unfnest 1.0
import "../dialogs"

Item {
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 4

        // Header
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Select components and quantities:" }
            Item { Layout.fillWidth: true }
            Button {
                text: "+ Add Component"
                onClicked: compDialog.openForAdd()
            }
            Button {
                text: "Edit"
                onClicked: {
                    if (componentList.currentIndex >= 0)
                        compDialog.openForEdit(componentList.currentIndex)
                }
            }
            Button {
                text: "Delete"
                onClicked: {
                    if (componentList.currentIndex >= 0)
                        deleteConfirmDialog.open()
                }
            }
        }

        // List
        ListView {
            id: componentList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: componentController.model
            currentIndex: -1

            header: Rectangle {
                width: componentList.width
                height: 30
                color: root.darkMode ? "#3a3a3a" : "#e8e8e8"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 14
                    spacing: 4
                    Label { text: "Preview"; Layout.preferredWidth: 60; font.bold: true }
                    Label { text: "Name"; Layout.fillWidth: true; font.bold: true }
                    Label { text: "Stock"; Layout.preferredWidth: 60; font.bold: true; horizontalAlignment: Text.AlignHCenter }
                    Label { text: "Quantity"; Layout.preferredWidth: 120; font.bold: true }
                }
            }

            delegate: Rectangle {
                width: componentList.width
                height: 50
                color: componentList.currentIndex === index
                    ? (root.darkMode ? "#4a5568" : "#cce5ff")
                    : (index % 2 === 0
                        ? (root.darkMode ? "#2d2d2d" : "#ffffff")
                        : (root.darkMode ? "#333333" : "#f8f8f8"))

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        componentList.currentIndex = index
                        forceActiveFocus()
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 14
                    spacing: 4

                    // DXF Preview thumbnail
                    DXFPreviewItem {
                        Layout.preferredWidth: 60
                        Layout.preferredHeight: 40
                        dxfFilename: model.dxfFilename
                        darkMode: root.darkMode
                    }

                    Label {
                        text: model.name
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }

                    Label {
                        text: model.inventoryCount
                        Layout.preferredWidth: 60
                        horizontalAlignment: Text.AlignHCenter
                        color: model.inventoryCount === 0 ? "#e53e3e" : (root.darkMode ? "#e0e0e0" : "#333333")
                    }

                    SpinBox {
                        id: qtySpinBox
                        Layout.preferredWidth: 120
                        from: 0
                        to: 9999
                        editable: true
                        value: model.quantity
                        onValueModified: componentController.setQuantity(index, value)
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
                                componentList.currentIndex = index
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
                                    componentController.setQuantity(index, newVal)
                                }
                            }
                        }
                        function onAccepted() {
                            qtySpinBox.value = qtySpinBox.valueFromText(qtySpinBox.contentItem.text, Qt.locale())
                            componentController.setQuantity(index, qtySpinBox.value)
                            qtySpinBox.focus = false
                        }
                        function onActiveFocusChanged() {
                            if (!qtySpinBox.contentItem.activeFocus) {
                                qtySpinBox.value = qtySpinBox.valueFromText(qtySpinBox.contentItem.text, Qt.locale())
                                componentController.setQuantity(index, qtySpinBox.value)
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
                text: componentList.currentIndex >= 0
                    ? "Are you sure you want to delete this component?\n\nThis will fail if the component is used in any products."
                    : ""
                wrapMode: Text.WordWrap
            }

            onAccepted: {
                let error = componentController.deleteComponent(componentList.currentIndex)
                if (error) {
                    cantDeleteLabel.text = error
                    cantDeleteDialog.open()
                }
            }
        }

        Dialog {
            id: cantDeleteDialog
            title: "Cannot Delete"
            modal: true
            anchors.centerIn: Overlay.overlay
            standardButtons: Dialog.Ok

            Label {
                id: cantDeleteLabel
                wrapMode: Text.WordWrap
            }
        }
    }

    // Component dialog
    ComponentDialog {
        id: compDialog
    }
}
