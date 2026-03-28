import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "dialogs"

Item {
    id: productsView

    // Header row
    Rectangle {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 36
        color: palette.alternateBase

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            spacing: 8

            Label {
                text: "Product"
                font.bold: true
                Layout.fillWidth: true
            }

            Label {
                text: "SKU"
                font.bold: true
                Layout.preferredWidth: 100
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Stock"
                font.bold: true
                Layout.preferredWidth: 60
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Target"
                font.bold: true
                Layout.preferredWidth: 60
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Reorder"
                font.bold: true
                Layout.preferredWidth: 60
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Vel/day"
                font.bold: true
                Layout.preferredWidth: 55
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "ABC"
                font.bold: true
                Layout.preferredWidth: 40
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Last Updated"
                font.bold: true
                Layout.preferredWidth: 90
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Action"
                font.bold: true
                Layout.preferredWidth: 80
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }

    // Separator line
    Rectangle {
        id: headerSep
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        height: 1
        color: palette.mid
    }

    ListView {
        id: listView
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: headerSep.bottom
        anchors.bottom: parent.bottom
        clip: true
        model: productInventoryController.model

        delegate: Rectangle {
            id: delegateRoot
            required property int index
            required property string sku
            required property string name
            required property int stock
            required property string lastUpdated
            required property int targetStock
            required property int reorderPoint
            required property string abcClass
            required property real velocity
            required property string stockStatus

            width: listView.width
            height: 50
            color: {
                if (stockStatus === "below_reorder")
                    return Qt.rgba(0.9, 0.2, 0.2, 0.12)
                if (stockStatus === "below_target")
                    return Qt.rgba(0.95, 0.75, 0.1, 0.12)
                return index % 2 === 0 ? "transparent" : Qt.rgba(palette.alternateBase.r,
                                                                  palette.alternateBase.g,
                                                                  palette.alternateBase.b, 0.3)
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 8

                // Product name
                Label {
                    text: name
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }

                // SKU
                Label {
                    text: sku
                    Layout.preferredWidth: 100
                    horizontalAlignment: Text.AlignHCenter
                    color: palette.placeholderText
                    elide: Text.ElideRight
                }

                // Stock level — color-coded
                Label {
                    text: stock.toString()
                    Layout.preferredWidth: 60
                    horizontalAlignment: Text.AlignHCenter
                    font.bold: true
                    color: {
                        if (stockStatus === "below_reorder")
                            return "#e53935"
                        if (stockStatus === "below_target")
                            return "#FB8C00"
                        return palette.windowText
                    }
                }

                // Target stock
                Label {
                    text: targetStock > 0 ? targetStock.toString() : "-"
                    Layout.preferredWidth: 60
                    horizontalAlignment: Text.AlignHCenter
                    color: palette.placeholderText
                }

                // Reorder point
                Label {
                    text: reorderPoint > 0 ? reorderPoint.toString() : "-"
                    Layout.preferredWidth: 60
                    horizontalAlignment: Text.AlignHCenter
                    color: palette.placeholderText
                }

                // Velocity (demand per day)
                Label {
                    text: velocity > 0 ? velocity.toFixed(2) : "-"
                    Layout.preferredWidth: 55
                    horizontalAlignment: Text.AlignHCenter
                    color: palette.placeholderText
                }

                // ABC class badge
                Item {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 20
                    Layout.alignment: Qt.AlignCenter

                    Rectangle {
                        anchors.centerIn: parent
                        width: 28
                        height: 18
                        radius: 3
                        visible: abcClass !== ""
                        color: {
                            if (abcClass === "A") return "#4CAF50"
                            if (abcClass === "B") return "#FF9800"
                            return "#9E9E9E"
                        }
                        Label {
                            anchors.centerIn: parent
                            text: abcClass
                            font.bold: true
                            font.pixelSize: 10
                            color: "white"
                        }
                    }
                }

                // Last updated
                Label {
                    text: lastUpdated
                    Layout.preferredWidth: 90
                    horizontalAlignment: Text.AlignHCenter
                    color: palette.placeholderText
                }

                // Adjust button
                Button {
                    text: "Adjust"
                    Layout.preferredWidth: 80
                    onClicked: {
                        productAdjustDialog.productSku = sku
                        productAdjustDialog.productName = name
                        productAdjustDialog.currentStock = stock
                        productAdjustDialog.open()
                    }
                }
            }
        }

        // Empty state
        Label {
            anchors.centerIn: parent
            visible: listView.count === 0
            text: appController.connectionOk
                  ? "No products found"
                  : "Not connected - check settings"
            color: palette.placeholderText
            font.pixelSize: 14
        }
    }

    ProductAdjustmentDialog {
        id: productAdjustDialog
    }
}
