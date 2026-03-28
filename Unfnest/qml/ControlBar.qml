import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "dialogs"

RowLayout {
    id: controlBar
    spacing: 8

    property int currentTabIndex: 0

    Button {
        text: "Clear All"
        visible: currentTabIndex !== 2
        onClicked: {
            productController.clearQuantities()
            componentController.clearQuantities()
        }
    }

    Button {
        text: "Recalculate"
        visible: currentTabIndex === 2
        onClicked: replenishmentController.recalculate()
        enabled: !replenishmentController.isLoading && !nestingController.isRunning
    }

    Button {
        text: "Refresh"
        onClicked: {
            if (currentTabIndex === 2) {
                replenishmentController.refresh()
            } else {
                componentController.refresh()
                productController.refresh()
            }
        }
    }

    Button {
        text: "Settings"
        onClicked: settingsDialog.open()
    }

    Item { Layout.fillWidth: true }

    // Nest button
    Button {
        id: nestBtn
        visible: !nestingController.isRunning
        font.bold: true
        implicitHeight: 40
        implicitWidth: 120
        onClicked: {
            if (currentTabIndex === 0) {
                nestingController.runFromProducts()
            } else if (currentTabIndex === 2) {
                replenishmentController.runReplenishmentNesting()
            } else {
                nestingController.runFromComponents()
            }
        }
        contentItem: Text {
            text: "Nest"
            font: nestBtn.font
            color: "white"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            color: nestBtn.down ? "#388E3C" : "#4CAF50"
            radius: 4
        }
    }

    // Stop button
    Button {
        id: stopBtn
        visible: nestingController.isRunning
        font.bold: true
        implicitHeight: 40
        implicitWidth: 120
        onClicked: nestingController.stopNesting()
        contentItem: Text {
            text: "Stop"
            font: stopBtn.font
            color: "white"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            color: stopBtn.down ? "#C62828" : "#f44336"
            radius: 4
        }
    }

    // Settings Dialog
    SettingsDialog {
        id: settingsDialog
    }
}
