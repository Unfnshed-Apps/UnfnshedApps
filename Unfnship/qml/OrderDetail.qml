import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "dialogs"

Rectangle {
    id: orderDetail
    color: palette.alternateBase

    property var order: shippingController.selectedOrder
    property bool hasOrder: order && Object.keys(order).length > 0

    ParcelDialog {
        id: parcelDialog
        onRequestRates: function(w, l, wd, h) {
            shippingController.getRates(orderDetail.order.order_id, w, l, wd, h)
        }
    }

    // Empty state
    Label {
        anchors.centerIn: parent
        visible: !orderDetail.hasOrder
        text: "Select an order to see details"
        color: palette.placeholderText
        font.pixelSize: 14
    }

    // Order details
    ScrollView {
        anchors.fill: parent
        anchors.margins: 16
        visible: orderDetail.hasOrder
        clip: true

        ColumnLayout {
            width: orderDetail.width - 32
            spacing: 16

            // Header
            ColumnLayout {
                spacing: 4
                Layout.fillWidth: true

                Label {
                    text: orderDetail.order.name || ""
                    font.pixelSize: 22
                    font.bold: true
                }
                Label {
                    text: orderDetail.order.customer_name || ""
                    font.pixelSize: 16
                }
                Label {
                    visible: orderDetail.order.email !== undefined && orderDetail.order.email !== ""
                    text: orderDetail.order.email || ""
                    font.pixelSize: 12
                    color: palette.placeholderText
                }
            }

            // Shipping Address
            GroupBox {
                title: "Shipping Address"
                Layout.fillWidth: true

                Label {
                    text: orderDetail.formatAddress(orderDetail.order.shipping_address)
                    wrapMode: Text.WordWrap
                    width: parent.width
                }
            }

            // Items
            GroupBox {
                title: "Items (" + (orderDetail.order.items ? orderDetail.order.items.length : 0) + ")"
                Layout.fillWidth: true

                ColumnLayout {
                    width: parent.width
                    spacing: 0

                    // Header row
                    Rectangle {
                        Layout.fillWidth: true
                        height: 24
                        color: Qt.rgba(0, 0, 0, 0.05)
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 4
                            anchors.rightMargin: 4
                            Label { text: "SKU"; font.bold: true; Layout.preferredWidth: 100 }
                            Label { text: "Item"; font.bold: true; Layout.fillWidth: true }
                            Label { text: "Qty"; font.bold: true; Layout.preferredWidth: 40; horizontalAlignment: Text.AlignHCenter }
                            Label { text: "Stock"; font.bold: true; Layout.preferredWidth: 50; horizontalAlignment: Text.AlignHCenter }
                            Label { text: ""; Layout.preferredWidth: 70 }
                        }
                    }

                    Repeater {
                        model: orderDetail.order.items || []
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            height: 32
                            color: index % 2 === 0 ? "transparent" : Qt.rgba(0, 0, 0, 0.03)

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 4
                                anchors.rightMargin: 4
                                spacing: 4

                                Label {
                                    text: modelData.sku || ""
                                    Layout.preferredWidth: 100
                                    elide: Text.ElideRight
                                    font.family: "Menlo"
                                    font.pixelSize: 11
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    Label {
                                        text: modelData.title || ""
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    Label {
                                        visible: modelData.variant_title !== undefined && modelData.variant_title !== ""
                                        text: modelData.variant_title || ""
                                        font.pixelSize: 10
                                        color: palette.placeholderText
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                }
                                Label {
                                    text: (modelData.quantity || 1).toString()
                                    Layout.preferredWidth: 40
                                    horizontalAlignment: Text.AlignHCenter
                                    font.bold: true
                                }
                                Label {
                                    text: (modelData.stock || 0).toString()
                                    Layout.preferredWidth: 50
                                    horizontalAlignment: Text.AlignHCenter
                                    color: modelData.in_stock ? "#43A047" : "#FB8C00"
                                    font.bold: true
                                }
                                Rectangle {
                                    Layout.preferredWidth: 70
                                    Layout.preferredHeight: 18
                                    radius: 3
                                    color: modelData.in_stock ? "#43A047" : "#FB8C00"
                                    Label {
                                        anchors.centerIn: parent
                                        text: modelData.in_stock ? "Ready" : "Low"
                                        font.pixelSize: 9
                                        font.bold: true
                                        color: "white"
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Note
            GroupBox {
                title: "Note"
                Layout.fillWidth: true
                visible: orderDetail.order.note !== undefined && orderDetail.order.note !== ""

                Label {
                    text: orderDetail.order.note || ""
                    wrapMode: Text.WordWrap
                    width: parent.width
                }
            }

            // Total
            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: "Total:"
                    font.pixelSize: 14
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                Label {
                    text: "$" + (orderDetail.order.total_price || "0.00")
                    font.pixelSize: 16
                    font.bold: true
                }
            }

            // Action buttons
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Button {
                    text: shippingController.ratesLoading ? "Loading..." : "Get Rates"
                    enabled: orderDetail.hasOrder && !shippingController.ratesLoading
                    Layout.fillWidth: true
                    onClicked: parcelDialog.open()
                }

                Button {
                    text: "Mark Fulfilled"
                    enabled: orderDetail.hasOrder
                    Layout.fillWidth: true
                    onClicked: {
                        // TODO: Wire to fulfill endpoint
                        console.log("Mark Fulfilled clicked for order", orderDetail.order.order_id)
                    }
                }
            }

            // Rates list
            GroupBox {
                title: "Available Rates (" + shippingController.rates.length + ")"
                Layout.fillWidth: true
                visible: shippingController.rates.length > 0

                ColumnLayout {
                    width: parent.width
                    spacing: 4

                    Repeater {
                        model: shippingController.rates
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            height: 44
                            color: index % 2 === 0 ? "transparent" : Qt.rgba(0, 0, 0, 0.03)
                            border.width: 1
                            border.color: Qt.rgba(0, 0, 0, 0.08)
                            radius: 4

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 8

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    Label {
                                        text: modelData.carrier || ""
                                        font.bold: true
                                        font.pixelSize: 13
                                    }
                                    Label {
                                        text: modelData.service || ""
                                        font.pixelSize: 11
                                        color: palette.placeholderText
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                }

                                Label {
                                    text: modelData.days ? modelData.days + "d" : ""
                                    Layout.preferredWidth: 36
                                    horizontalAlignment: Text.AlignHCenter
                                    color: palette.placeholderText
                                    font.pixelSize: 11
                                }

                                Label {
                                    text: "$" + modelData.amount
                                    font.bold: true
                                    Layout.preferredWidth: 60
                                    horizontalAlignment: Text.AlignRight
                                }

                                Button {
                                    text: "Print"
                                    Layout.preferredWidth: 60
                                    onClicked: {
                                        // TODO: Wire to label purchase + printer
                                        console.log("Print", modelData.rate_id)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }

    function formatAddress(addr) {
        if (!addr) return "(no address)"
        let parts = []
        if (addr.name) parts.push(addr.name)
        if (addr.company) parts.push(addr.company)
        if (addr.address1) parts.push(addr.address1)
        if (addr.address2) parts.push(addr.address2)
        let cityLine = ""
        if (addr.city) cityLine += addr.city
        if (addr.province_code || addr.province) cityLine += ", " + (addr.province_code || addr.province)
        if (addr.zip) cityLine += " " + addr.zip
        if (cityLine) parts.push(cityLine)
        if (addr.country) parts.push(addr.country)
        if (addr.phone) parts.push("Tel: " + addr.phone)
        return parts.join("\n")
    }
}
