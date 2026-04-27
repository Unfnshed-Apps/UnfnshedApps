import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "dialogs"

Item {
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        Label {
            text: "Preview:"
            font.bold: true
        }

        // Sheet preview
        SheetPreview {
            id: sheetPreview
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        // Sheet navigation
        SheetNavigator {
            Layout.fillWidth: true
        }

        // Export
        Button {
            id: exportBtn
            enabled: nestingController.hasResult
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: sheetPreview.width * 0.5
            font.bold: true
            implicitHeight: 40
            onClicked: {
                let msg = nestingController.exportResult(prototypeCheck.checked)
                exportResultDialog.text = msg
                exportResultDialog.open()
            }
            contentItem: Text {
                text: "Send to UnfnCNC"
                font: exportBtn.font
                color: "white"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                opacity: exportBtn.enabled ? 1.0 : 0.5
            }
            background: Rectangle {
                color: !exportBtn.enabled ? "#7B1FA2" : exportBtn.down ? "#7B1FA2" : "#9C27B0"
                radius: 4
                opacity: exportBtn.enabled ? 1.0 : 0.5
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 4

            CheckBox {
                id: prototypeCheck
                text: "Prototype"
            }

            Rectangle {
                width: 18; height: 18; radius: 9
                color: "transparent"
                border.color: root.darkMode ? "#888" : "#999"
                border.width: 1

                Label {
                    anchors.centerIn: parent
                    text: "?"
                    font.pixelSize: 11
                    font.bold: true
                    color: root.darkMode ? "#888" : "#999"
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: prototypeHelpDialog.open()
                }
            }
        }

        Dialog {
            id: prototypeHelpDialog
            title: "Prototype Mode"
            modal: true
            anchors.centerIn: Overlay.overlay
            standardButtons: Dialog.Ok
            width: 360

            Label {
                text: "Checking Prototype will not add the nested components to inventory after cutting. The sheets will be added to the separate prototype queue. These sheets can be pulled into UnfnCNC by clicking the \"Load Prototype\" button in UnfnCNC."
                wrapMode: Text.WordWrap
                width: parent.width
            }
        }

        // Results
        GroupBox {
            title: "Results"
            Layout.fillWidth: true

            Label {
                text: nestingController.resultsText
                wrapMode: Text.WordWrap
                width: parent.width
            }
        }
    }

    Dialog {
        id: exportResultDialog
        title: "Export Complete"
        modal: true
        anchors.centerIn: Overlay.overlay
        standardButtons: Dialog.Ok
        property alias text: exportLabel.text
        Label {
            id: exportLabel
            wrapMode: Text.WordWrap
        }
    }
}
