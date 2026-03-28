import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    spacing: 8

    Button {
        text: "< Previous"
        enabled: nestingController.canGoPrev
        onClicked: nestingController.prevSheet()
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2

        Label {
            text: {
                if (!nestingController.hasResult)
                    return "No sheets"
                var base = "Sheet " + (nestingController.currentSheetIndex + 1) + " of " + nestingController.totalSheets
                if (nestingController.isRunning)
                    base += "  (live)"
                return base
            }
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }

        Label {
            text: nestingController.currentSheetUtilization
            visible: text !== ""
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
            font.pointSize: 11
            opacity: 0.8
        }

        Label {
            text: nestingController.sheetGroupText
            visible: text !== "" && !nestingController.isRunning
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
            font.pointSize: 10
            opacity: 0.6
        }

        CheckBox {
            text: "Auto-Follow"
            visible: nestingController.isRunning
            checked: nestingController.autoFollow
            onToggled: nestingController.setAutoFollow(checked)
            Layout.alignment: Qt.AlignHCenter
        }
    }

    Button {
        text: "Next >"
        enabled: nestingController.canGoNext
        onClicked: nestingController.nextSheet()
    }
}
