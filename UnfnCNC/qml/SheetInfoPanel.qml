import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

GroupBox {
    title: "Sheet Info"

    ColumnLayout {
        anchors.fill: parent
        spacing: 6

        Label {
            text: cuttingController.jobName
            font.pixelSize: 12
            font.bold: true
        }

        Label {
            text: cuttingController.sheetText
            visible: cuttingController.sheetText !== ""
        }

        Label {
            text: cuttingController.gcodeText
            visible: cuttingController.gcodeText !== ""
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Qt.rgba(0.5, 0.5, 0.5, 0.3)
            visible: cuttingController.isCutting
        }

        Label {
            text: "Parts on this sheet:"
            font.pixelSize: 11
            font.bold: true
            visible: cuttingController.isCutting && cuttingController.partsText !== ""
        }

        Label {
            text: cuttingController.partsText
            visible: cuttingController.partsText !== ""
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Label {
            text: cuttingController.ordersText
            visible: cuttingController.ordersText !== ""
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Label {
            text: cuttingController.bundleText
            visible: cuttingController.bundleText !== ""
            font.bold: true
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Item { Layout.fillHeight: true }

        Button {
            text: "Release Sheet"
            visible: cuttingController.isCutting
            palette.buttonText: "#cc6600"
            onClicked: releaseConfirmDialog.open()
        }
    }
}
