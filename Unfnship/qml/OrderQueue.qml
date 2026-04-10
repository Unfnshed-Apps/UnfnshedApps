import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: orderQueue

    // Header
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
                text: "Order"
                font.bold: true
                Layout.preferredWidth: 80
            }

            Label {
                text: "Customer"
                font.bold: true
                Layout.fillWidth: true
            }

            Label {
                text: "Items"
                font.bold: true
                Layout.preferredWidth: 50
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Total"
                font.bold: true
                Layout.preferredWidth: 70
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Date"
                font.bold: true
                Layout.preferredWidth: 90
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                text: "Status"
                font.bold: true
                Layout.preferredWidth: 90
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }

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
        model: shippingController.model

        delegate: Rectangle {
            id: delegateRoot
            required property int index
            required property int orderId
            required property string orderNumber
            required property string customerName
            required property int itemCount
            required property bool readyToShip
            required property string createdAt
            required property string totalPrice
            required property string note

            width: listView.width
            height: 50
            color: {
                if (listView.currentIndex === index)
                    return Qt.rgba(palette.highlight.r, palette.highlight.g, palette.highlight.b, 0.2)
                if (!readyToShip)
                    return Qt.rgba(0.95, 0.75, 0.1, 0.08)
                return index % 2 === 0 ? "transparent" : Qt.rgba(palette.alternateBase.r,
                                                                  palette.alternateBase.g,
                                                                  palette.alternateBase.b, 0.3)
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    listView.currentIndex = delegateRoot.index
                    shippingController.selectOrder(delegateRoot.index)
                }
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 8

                Label {
                    text: delegateRoot.orderNumber
                    Layout.preferredWidth: 80
                    font.bold: true
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Label {
                        text: delegateRoot.customerName
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Label {
                        visible: delegateRoot.note !== ""
                        text: delegateRoot.note
                        font.pixelSize: 11
                        opacity: 0.6
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                Label {
                    text: delegateRoot.itemCount.toString()
                    Layout.preferredWidth: 50
                    horizontalAlignment: Text.AlignHCenter
                }

                Label {
                    text: "$" + delegateRoot.totalPrice
                    Layout.preferredWidth: 70
                    horizontalAlignment: Text.AlignHCenter
                    color: palette.placeholderText
                }

                Label {
                    text: delegateRoot.createdAt
                    Layout.preferredWidth: 90
                    horizontalAlignment: Text.AlignHCenter
                    color: palette.placeholderText
                }

                // Ready badge
                Item {
                    Layout.preferredWidth: 90
                    Layout.preferredHeight: 20
                    Layout.alignment: Qt.AlignCenter

                    Rectangle {
                        anchors.centerIn: parent
                        width: 80
                        height: 18
                        radius: 3
                        color: delegateRoot.readyToShip ? "#43A047" : "#FB8C00"
                        Label {
                            anchors.centerIn: parent
                            text: delegateRoot.readyToShip ? "Ready" : "Low Stock"
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
                  ? "No unfulfilled orders"
                  : "Not connected - check settings"
            color: palette.placeholderText
            font.pixelSize: 14
        }
    }
}
