import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: replenishmentTab

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        // Header
        Rectangle {
            Layout.fillWidth: true
            height: 32
            color: palette.alternateBase

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 8

                Label { text: "Product"; font.bold: true; Layout.fillWidth: true }
                Label { text: "SKU"; font.bold: true; Layout.preferredWidth: 100; horizontalAlignment: Text.AlignHCenter }
                Label { text: "Stock"; font.bold: true; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                Label { text: "Target"; font.bold: true; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                Label { text: "Deficit"; font.bold: true; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                Label { text: "Status"; font.bold: true; Layout.preferredWidth: 95; horizontalAlignment: Text.AlignHCenter }
            }
        }

        // Separator
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: palette.mid
        }

        // Table
        ListView {
            id: listView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: replenishmentController.model

            delegate: Rectangle {
                id: delegateRoot
                required property int index
                required property string sku
                required property string name
                required property int stock
                required property int targetStock
                required property string stockStatus
                required property int deficit

                width: listView.width
                height: 36
                color: {
                    if (stockStatus === "below_reorder")
                        return Qt.rgba(0.9, 0.2, 0.2, 0.15)
                    if (stockStatus === "below_target")
                        return Qt.rgba(0.95, 0.75, 0.1, 0.15)
                    return index % 2 === 0 ? "transparent" : Qt.rgba(palette.alternateBase.r,
                                                                      palette.alternateBase.g,
                                                                      palette.alternateBase.b, 0.3)
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 8

                    Label {
                        text: delegateRoot.name
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }

                    Label {
                        text: delegateRoot.sku
                        Layout.preferredWidth: 100
                        horizontalAlignment: Text.AlignHCenter
                        color: palette.placeholderText
                        elide: Text.ElideRight
                    }

                    Label {
                        text: delegateRoot.stock.toString()
                        Layout.preferredWidth: 60
                        horizontalAlignment: Text.AlignHCenter
                        font.bold: true
                        color: delegateRoot.stock <= 0 ? "#e53935" : palette.windowText
                    }

                    Label {
                        text: delegateRoot.targetStock.toString()
                        Layout.preferredWidth: 60
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Label {
                        text: delegateRoot.deficit > 0 ? delegateRoot.deficit.toString() : "-"
                        Layout.preferredWidth: 60
                        horizontalAlignment: Text.AlignHCenter
                        font.bold: delegateRoot.deficit > 0
                        color: delegateRoot.deficit > 0 ? "#e53935" : palette.placeholderText
                    }

                    // Status badge
                    Item {
                        Layout.preferredWidth: 95
                        Layout.preferredHeight: 20
                        Layout.alignment: Qt.AlignCenter

                        Rectangle {
                            anchors.centerIn: parent
                            width: 85
                            height: 18
                            radius: 3
                            color: {
                                if (delegateRoot.stockStatus === "below_reorder") return "#e53935"
                                if (delegateRoot.stockStatus === "below_target") return "#FB8C00"
                                return "#43A047"
                            }
                            Label {
                                anchors.centerIn: parent
                                text: {
                                    if (delegateRoot.stockStatus === "below_reorder")
                                        return "Below Reorder"
                                    if (delegateRoot.stockStatus === "below_target")
                                        return "Below Target"
                                    return "Adequate"
                                }
                                font.pixelSize: 10
                                font.bold: true
                                color: "white"
                            }
                        }
                    }
                }
            }

            // Empty state
            Label {
                anchors.centerIn: parent
                visible: listView.count === 0
                text: appController.connectionOk
                      ? "Click Refresh to load replenishment data"
                      : "Not connected - check settings"
                color: palette.placeholderText
                font.pixelSize: 14
            }
        }
    }

    Component.onCompleted: {
        replenishmentController.refresh()
    }
}
