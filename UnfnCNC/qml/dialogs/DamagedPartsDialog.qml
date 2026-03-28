import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import UnfnCNC 1.0

Dialog {
    id: root
    title: "Report Damaged Parts"
    width: 800
    height: 500
    anchors.centerIn: parent
    modal: true
    standardButtons: Dialog.Ok | Dialog.Cancel

    property bool darkMode: {
        let bg = palette.window
        let luminance = (0.299 * bg.r + 0.587 * bg.g + 0.114 * bg.b)
        return luminance < 0.5
    }

    onAccepted: damageController.submitDamage()
    onRejected: damageController.cancelDamage()

    contentItem: RowLayout {
        spacing: 12

        // ==================== Left side ====================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 3
            spacing: 6

            // Clickable preview mode
            ClickablePreviewItem {
                Layout.fillWidth: true
                Layout.fillHeight: true
                darkMode: root.darkMode
                visible: damageController.hasClickablePreview

                ToolTip.visible: tooltipText !== ""
                ToolTip.text: tooltipText
            }

            // Fallback mode: read-only sheet preview
            SheetPreviewItem {
                Layout.fillWidth: true
                Layout.fillHeight: true
                darkMode: root.darkMode
                visible: !damageController.hasClickablePreview
            }

            // Instruction label (clickable mode only)
            Label {
                text: "Click parts to mark them as damaged"
                horizontalAlignment: Text.AlignHCenter
                Layout.fillWidth: true
                color: "#666"
                font.italic: true
                visible: damageController.hasClickablePreview
            }

            // Legend (clickable mode only)
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 8
                visible: damageController.hasClickablePreview

                Rectangle {
                    width: 16; height: 16
                    color: "#dcdcdc"
                    border.color: "#888"
                    radius: 2
                }
                Label { text: "Normal" }

                Item { width: 10 }

                Rectangle {
                    width: 16; height: 16
                    color: "#dc3232"
                    border.color: "#888"
                    radius: 2
                }
                Label { text: "Damaged" }
            }
        }

        // ==================== Right side ====================
        ColumnLayout {
            Layout.fillHeight: true
            Layout.preferredWidth: 2
            spacing: 6

            // -- Clickable mode: summary table --
            Label {
                text: "Damage Summary"
                font.pixelSize: 12
                font.bold: true
                visible: damageController.hasClickablePreview
            }

            // Header row
            RowLayout {
                Layout.fillWidth: true
                visible: damageController.hasClickablePreview
                spacing: 4

                Label {
                    text: "Component"
                    font.bold: true
                    Layout.fillWidth: true
                }
                Label {
                    text: "Qty"
                    font.bold: true
                    Layout.preferredWidth: 40
                    horizontalAlignment: Text.AlignHCenter
                }
                Label {
                    text: "Dmg"
                    font.bold: true
                    Layout.preferredWidth: 40
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                visible: damageController.hasClickablePreview
                model: damageController.summaryModel

                delegate: RowLayout {
                    width: ListView.view.width
                    spacing: 4

                    Label {
                        text: model.name
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Label {
                        text: model.quantity
                        Layout.preferredWidth: 40
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Label {
                        text: model.damaged
                        Layout.preferredWidth: 40
                        horizontalAlignment: Text.AlignHCenter
                        color: model.damaged > 0 ? "#c80000" : palette.text
                    }
                }
            }

            // -- Fallback mode: spinbox table --
            Label {
                text: "Select damaged quantities:"
                font.pixelSize: 12
                font.bold: true
                visible: !damageController.hasClickablePreview
            }

            // Header row for fallback
            RowLayout {
                Layout.fillWidth: true
                visible: !damageController.hasClickablePreview
                spacing: 4

                Label {
                    text: "Component"
                    font.bold: true
                    Layout.fillWidth: true
                }
                Label {
                    text: "On Sheet"
                    font.bold: true
                    Layout.preferredWidth: 60
                    horizontalAlignment: Text.AlignHCenter
                }
                Label {
                    text: "Damaged"
                    font.bold: true
                    Layout.preferredWidth: 80
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                visible: !damageController.hasClickablePreview
                model: damageController.fallbackPartsModel

                delegate: RowLayout {
                    width: ListView.view.width
                    spacing: 4

                    Label {
                        text: model.componentName
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Label {
                        text: model.quantity
                        Layout.preferredWidth: 60
                        horizontalAlignment: Text.AlignHCenter
                    }
                    SpinBox {
                        from: 0
                        to: model.quantity
                        value: model.damaged
                        Layout.preferredWidth: 80
                        onValueModified: damageController.setFallbackDamage(index, value)
                    }
                }
            }

            // Orders text
            Label {
                text: damageController.ordersText
                visible: damageController.ordersText !== ""
                wrapMode: Text.WordWrap
                color: "#666"
                Layout.fillWidth: true
            }
        }
    }

    // ==================== Ambiguous Resolution Sub-dialog ====================

    AmbiguousResolutionDialog {
        id: ambiguousDialog
    }

    Connections {
        target: damageController
        function onAmbiguousResolutionNeeded(groupIndex, candidatesJson, damagedCount) {
            ambiguousDialog.groupIndex = groupIndex
            ambiguousDialog.candidatesJson = candidatesJson
            ambiguousDialog.damagedCount = damagedCount
            ambiguousDialog.open()
        }
        function onDamageReportReady(damagesJson) {
            root.close()
        }
    }
}
