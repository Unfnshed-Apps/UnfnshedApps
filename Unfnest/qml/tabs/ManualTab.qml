import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 4

        // Header
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Manual nests (pre-built sheet layouts):" }
            Item { Layout.fillWidth: true }
            Button {
                text: "+ Create New Manual Nest"
                // Wave 2 opens the drag-and-drop editor window. For now the
                // button is visible but inert so the UI matches the final shape.
                enabled: false
                ToolTip.visible: hovered
                ToolTip.text: "Editor coming in the next update."
            }
            Button {
                text: "Delete"
                enabled: manualList.currentIndex >= 0
                onClicked: deleteConfirmDialog.open()
            }
        }

        // List
        ListView {
            id: manualList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: manualController.model
            currentIndex: -1

            header: Rectangle {
                width: manualList.width
                height: 30
                color: root.darkMode ? "#3a3a3a" : "#e8e8e8"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 14
                    spacing: 4
                    Label { text: "Name"; Layout.preferredWidth: 180; font.bold: true }
                    Label { text: "Contents"; Layout.fillWidth: true; font.bold: true }
                    Label { text: "Sheets"; Layout.preferredWidth: 60; font.bold: true; horizontalAlignment: Text.AlignHCenter }
                    Label { text: "Override"; Layout.preferredWidth: 80; font.bold: true; horizontalAlignment: Text.AlignHCenter }
                }
            }

            delegate: Rectangle {
                width: manualList.width
                height: 40
                color: manualList.currentIndex === index
                    ? (root.darkMode ? "#4a5568" : "#cce5ff")
                    : (index % 2 === 0
                        ? (root.darkMode ? "#2d2d2d" : "#ffffff")
                        : (root.darkMode ? "#333333" : "#f8f8f8"))

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        manualList.currentIndex = index
                        forceActiveFocus()
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 14
                    spacing: 4

                    Label {
                        text: model.name
                        Layout.preferredWidth: 180
                        elide: Text.ElideRight
                    }
                    Label {
                        text: model.summary
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    Label {
                        text: model.sheetCount
                        Layout.preferredWidth: 60
                        horizontalAlignment: Text.AlignHCenter
                    }
                    CheckBox {
                        Layout.preferredWidth: 80
                        Layout.alignment: Qt.AlignHCenter
                        checked: model.overrideEnabled
                        onToggled: manualController.setOverrideEnabled(index, checked)
                        // Click anywhere inside should select the row too
                        MouseArea {
                            anchors.fill: parent
                            z: 100
                            onPressed: function(mouse) {
                                manualList.currentIndex = index
                                mouse.accepted = false
                            }
                        }
                    }
                }
            }

            ScrollBar.vertical: ScrollBar {}

            // Empty-state hint
            Label {
                anchors.centerIn: parent
                visible: manualList.count === 0
                text: "No manual nests yet.\nUse \"Create New Manual Nest\" to build a pre-nested sheet layout."
                horizontalAlignment: Text.AlignHCenter
                color: root.darkMode ? "#888" : "#666"
                wrapMode: Text.WordWrap
            }
        }

        // Delete confirmation
        Dialog {
            id: deleteConfirmDialog
            title: "Confirm Delete"
            modal: true
            anchors.centerIn: Overlay.overlay
            standardButtons: Dialog.Yes | Dialog.No

            Label {
                text: manualList.currentIndex >= 0
                    ? "Delete manual nest? This cannot be undone."
                    : ""
                wrapMode: Text.WordWrap
            }

            onAccepted: manualController.deleteNest(manualList.currentIndex)
        }
    }

    // Refresh the list whenever this tab becomes visible
    onVisibleChanged: {
        if (visible) manualController.refresh()
    }
}
