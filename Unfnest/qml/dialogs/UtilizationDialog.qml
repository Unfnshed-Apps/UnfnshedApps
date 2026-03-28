import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

Dialog {
    id: utilizationDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 400
    title: "Utilization Calculator"
    standardButtons: Dialog.Close

    ColumnLayout {
        width: utilizationDialog.availableWidth
        spacing: 12

        Button {
            text: "Select DXF File..."
            Layout.alignment: Qt.AlignHCenter
            onClicked: fileDialog.open()
        }

        Label {
            text: "DXF file must use these layer names:\n" +
                  "  Sheet Boundary — full sheet rectangle\n" +
                  "  Edge Margin — usable area inside margins\n" +
                  "  Outline — closed part outlines\n" +
                  "  Internal — through-cut holes (subtracted)\n" +
                  "  Pocket — partial-depth cuts (ignored)"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font.pixelSize: 11
            color: palette.placeholderText
        }

        Label {
            text: utilizationController.filename
            visible: utilizationController.filename !== ""
            Layout.fillWidth: true
            elide: Text.ElideMiddle
            horizontalAlignment: Text.AlignHCenter
            color: palette.placeholderText
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: palette.mid
            visible: utilizationController.utilization !== "" || utilizationController.errorText !== ""
        }

        // Error display
        Label {
            text: utilizationController.errorText
            visible: utilizationController.errorText !== ""
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: "red"
        }

        // Results section
        ColumnLayout {
            spacing: 8
            Layout.fillWidth: true
            visible: utilizationController.utilization !== ""

            // Primary utilization
            Label {
                text: utilizationController.utilization
                font.pixelSize: 36
                font.bold: true
                Layout.alignment: Qt.AlignHCenter
                color: palette.windowText
            }

            Label {
                text: "Usable Area Utilization"
                font.pixelSize: 12
                Layout.alignment: Qt.AlignHCenter
                color: palette.placeholderText
            }

            // Secondary utilization
            Label {
                text: utilizationController.sheetUtilization + "  Sheet Utilization"
                font.pixelSize: 14
                Layout.alignment: Qt.AlignHCenter
                color: palette.placeholderText
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: palette.mid
            }

            // Details grid
            GridLayout {
                columns: 2
                Layout.fillWidth: true
                columnSpacing: 12
                rowSpacing: 4

                Label { text: "Parts:"; font.bold: true }
                Label { text: utilizationController.partCount }

                Label { text: "Part Area:"; font.bold: true }
                Label { text: utilizationController.partArea.toFixed(1) + " sq units" }

                Label { text: "Usable Area:"; font.bold: true }
                Label { text: utilizationController.usableArea.toFixed(1) + " sq units" }

                Label { text: "Sheet Area:"; font.bold: true }
                Label { text: utilizationController.sheetArea.toFixed(1) + " sq units" }
            }
        }
    }

    FileDialog {
        id: fileDialog
        title: "Select DXF File"
        nameFilters: ["DXF Files (*.dxf)"]
        fileMode: FileDialog.OpenFile
        onAccepted: utilizationController.calculateFromFile(selectedFile)
    }
}
