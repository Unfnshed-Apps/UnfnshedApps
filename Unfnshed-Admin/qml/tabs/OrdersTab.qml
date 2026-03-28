import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: ordersTab

    // Column width constants
    readonly property int colW_orderNum: 80
    readonly property int colW_customer: 140
    readonly property int colW_skus: 200
    readonly property int colW_total: 80
    readonly property int colW_shopify: 90
    readonly property int colW_production: 90
    readonly property int colW_created: 110
    readonly property int colW_email: 180
    readonly property int colW_phone: 120
    readonly property int colW_subtotal: 80
    readonly property int colW_tax: 70
    readonly property int colW_discounts: 80
    readonly property int colW_shipping: 80
    readonly property int colW_financial: 100
    readonly property int colW_note: 200
    readonly property int colW_tags: 150
    readonly property int colW_source: 80
    readonly property int colW_shopifyId: 140
    readonly property int colW_displayName: 80
    readonly property int colW_nestedAt: 110
    readonly property int colW_cutAt: 110
    readonly property int colW_packedAt: 110
    readonly property int colW_syncedAt: 110
    readonly property int colW_processedAt: 110
    readonly property int colW_cancelledAt: 110
    readonly property int colW_cancelReason: 120
    readonly property int colW_closedAt: 110
    readonly property int colW_shipAddr: 200
    readonly property int colW_billAddr: 200
    readonly property int colW_discCodes: 120
    readonly property int colW_shipMethod: 120
    readonly property int colW_payMethod: 120
    readonly property int colW_landing: 200
    readonly property int colW_referring: 200

    // Compute total content width from visible columns
    function contentWidth() {
        var w = 16 // left + right margin
        if (col_orderNumber.checked) w += colW_orderNum + 4
        if (col_customer.checked) w += colW_customer + 4
        if (col_skus.checked) w += colW_skus + 4
        if (col_total.checked) w += colW_total + 4
        if (col_shopify.checked) w += colW_shopify + 4
        if (col_production.checked) w += colW_production + 4
        if (col_created.checked) w += colW_created + 4
        if (col_email.checked) w += colW_email + 4
        if (col_phone.checked) w += colW_phone + 4
        if (col_subtotal.checked) w += colW_subtotal + 4
        if (col_tax.checked) w += colW_tax + 4
        if (col_discounts.checked) w += colW_discounts + 4
        if (col_shippingCost.checked) w += colW_shipping + 4
        if (col_financial.checked) w += colW_financial + 4
        if (col_note.checked) w += colW_note + 4
        if (col_tags.checked) w += colW_tags + 4
        if (col_source.checked) w += colW_source + 4
        if (col_shopifyId.checked) w += colW_shopifyId + 4
        if (col_displayName.checked) w += colW_displayName + 4
        if (col_nestedAt.checked) w += colW_nestedAt + 4
        if (col_cutAt.checked) w += colW_cutAt + 4
        if (col_packedAt.checked) w += colW_packedAt + 4
        if (col_syncedAt.checked) w += colW_syncedAt + 4
        if (col_processedAt.checked) w += colW_processedAt + 4
        if (col_cancelledAt.checked) w += colW_cancelledAt + 4
        if (col_cancelReason.checked) w += colW_cancelReason + 4
        if (col_closedAt.checked) w += colW_closedAt + 4
        if (col_shipAddr.checked) w += colW_shipAddr + 4
        if (col_billAddr.checked) w += colW_billAddr + 4
        if (col_discCodes.checked) w += colW_discCodes + 4
        if (col_shipMethod.checked) w += colW_shipMethod + 4
        if (col_payMethod.checked) w += colW_payMethod + 4
        if (col_landing.checked) w += colW_landing + 4
        if (col_referring.checked) w += colW_referring + 4
        return Math.max(w, ordersTab.width - 16)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 0

        // ── Filter Row ─────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 8
            spacing: 8

            Label { text: "Filter:" }

            ComboBox {
                id: filterCombo
                model: orderController.filterOptions
                onCurrentTextChanged: orderController.setFilter(currentText)
            }

            Item { Layout.fillWidth: true }

            Button {
                text: columnToggles.visible ? "Hide Columns" : "Columns"
                onClicked: columnToggles.visible = !columnToggles.visible
            }

            Button {
                text: "Refresh"
                onClicked: orderController.refresh()
            }
        }

        // ── Column Toggles ───────────────────────────────────
        Flow {
            id: columnToggles
            Layout.fillWidth: true
            Layout.bottomMargin: 8
            visible: false
            spacing: 0

            CheckBox { id: col_orderNumber; text: "Order #"; checked: true }
            CheckBox { id: col_customer; text: "Customer"; checked: true }
            CheckBox { id: col_skus; text: "SKUs"; checked: true }
            CheckBox { id: col_total; text: "Total"; checked: true }
            CheckBox { id: col_shopify; text: "Shopify"; checked: true }
            CheckBox { id: col_production; text: "Production"; checked: true }
            CheckBox { id: col_created; text: "Created"; checked: true }
            CheckBox { id: col_email; text: "Email"; checked: false }
            CheckBox { id: col_phone; text: "Phone"; checked: false }
            CheckBox { id: col_subtotal; text: "Subtotal"; checked: false }
            CheckBox { id: col_tax; text: "Tax"; checked: false }
            CheckBox { id: col_discounts; text: "Discounts"; checked: false }
            CheckBox { id: col_shippingCost; text: "Shipping Cost"; checked: false }
            CheckBox { id: col_financial; text: "Financial"; checked: false }
            CheckBox { id: col_note; text: "Note"; checked: false }
            CheckBox { id: col_tags; text: "Tags"; checked: false }
            CheckBox { id: col_source; text: "Source"; checked: false }
            CheckBox { id: col_shopifyId; text: "Shopify ID"; checked: false }
            CheckBox { id: col_displayName; text: "Display Name"; checked: false }
            CheckBox { id: col_nestedAt; text: "Nested At"; checked: false }
            CheckBox { id: col_cutAt; text: "Cut At"; checked: false }
            CheckBox { id: col_packedAt; text: "Packed At"; checked: false }
            CheckBox { id: col_syncedAt; text: "Synced At"; checked: false }
            CheckBox { id: col_processedAt; text: "Processed At"; checked: false }
            CheckBox { id: col_cancelledAt; text: "Cancelled At"; checked: false }
            CheckBox { id: col_cancelReason; text: "Cancel Reason"; checked: false }
            CheckBox { id: col_closedAt; text: "Closed At"; checked: false }
            CheckBox { id: col_shipAddr; text: "Shipping Addr"; checked: false }
            CheckBox { id: col_billAddr; text: "Billing Addr"; checked: false }
            CheckBox { id: col_discCodes; text: "Discount Codes"; checked: false }
            CheckBox { id: col_shipMethod; text: "Shipping Method"; checked: false }
            CheckBox { id: col_payMethod; text: "Payment Method"; checked: false }
            CheckBox { id: col_landing; text: "Landing Site"; checked: false }
            CheckBox { id: col_referring; text: "Referring Site"; checked: false }
        }

        // ── Scrollable Table Area ────────────────────────────
        Flickable {
            id: tableFlickable
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: ordersTab.contentWidth()
            contentHeight: tableColumn.height
            flickableDirection: Flickable.HorizontalFlick
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: tableColumn
                width: tableFlickable.contentWidth

                // ── Column Headers ───────────────────────────
                Rectangle {
                    width: parent.width
                    height: 32
                    color: palette.alternateBase

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        spacing: 4

                        Label {
                            text: "Order #"; font.bold: true
                            Layout.preferredWidth: colW_orderNum
                            visible: col_orderNumber.checked
                        }
                        Label {
                            text: "Customer"; font.bold: true
                            Layout.preferredWidth: colW_customer
                            visible: col_customer.checked
                        }
                        Label {
                            text: "SKUs"; font.bold: true
                            Layout.preferredWidth: colW_skus
                            visible: col_skus.checked
                        }
                        Label {
                            text: "Total"; font.bold: true
                            Layout.preferredWidth: colW_total
                            horizontalAlignment: Text.AlignRight
                            visible: col_total.checked
                        }
                        Label {
                            text: "Shopify"; font.bold: true
                            Layout.preferredWidth: colW_shopify
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_shopify.checked
                        }
                        Label {
                            text: "Production"; font.bold: true
                            Layout.preferredWidth: colW_production
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_production.checked
                        }
                        Label {
                            text: "Created"; font.bold: true
                            Layout.preferredWidth: colW_created
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_created.checked
                        }
                        Label {
                            text: "Email"; font.bold: true
                            Layout.preferredWidth: colW_email
                            visible: col_email.checked
                        }
                        Label {
                            text: "Phone"; font.bold: true
                            Layout.preferredWidth: colW_phone
                            visible: col_phone.checked
                        }
                        Label {
                            text: "Subtotal"; font.bold: true
                            Layout.preferredWidth: colW_subtotal
                            horizontalAlignment: Text.AlignRight
                            visible: col_subtotal.checked
                        }
                        Label {
                            text: "Tax"; font.bold: true
                            Layout.preferredWidth: colW_tax
                            horizontalAlignment: Text.AlignRight
                            visible: col_tax.checked
                        }
                        Label {
                            text: "Discounts"; font.bold: true
                            Layout.preferredWidth: colW_discounts
                            horizontalAlignment: Text.AlignRight
                            visible: col_discounts.checked
                        }
                        Label {
                            text: "Shipping $"; font.bold: true
                            Layout.preferredWidth: colW_shipping
                            horizontalAlignment: Text.AlignRight
                            visible: col_shippingCost.checked
                        }
                        Label {
                            text: "Financial"; font.bold: true
                            Layout.preferredWidth: colW_financial
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_financial.checked
                        }
                        Label {
                            text: "Note"; font.bold: true
                            Layout.preferredWidth: colW_note
                            visible: col_note.checked
                        }
                        Label {
                            text: "Tags"; font.bold: true
                            Layout.preferredWidth: colW_tags
                            visible: col_tags.checked
                        }
                        Label {
                            text: "Source"; font.bold: true
                            Layout.preferredWidth: colW_source
                            visible: col_source.checked
                        }
                        Label {
                            text: "Shopify ID"; font.bold: true
                            Layout.preferredWidth: colW_shopifyId
                            visible: col_shopifyId.checked
                        }
                        Label {
                            text: "Name"; font.bold: true
                            Layout.preferredWidth: colW_displayName
                            visible: col_displayName.checked
                        }
                        Label {
                            text: "Nested At"; font.bold: true
                            Layout.preferredWidth: colW_nestedAt
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_nestedAt.checked
                        }
                        Label {
                            text: "Cut At"; font.bold: true
                            Layout.preferredWidth: colW_cutAt
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_cutAt.checked
                        }
                        Label {
                            text: "Packed At"; font.bold: true
                            Layout.preferredWidth: colW_packedAt
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_packedAt.checked
                        }
                        Label {
                            text: "Synced At"; font.bold: true
                            Layout.preferredWidth: colW_syncedAt
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_syncedAt.checked
                        }
                        Label {
                            text: "Processed At"; font.bold: true
                            Layout.preferredWidth: colW_processedAt
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_processedAt.checked
                        }
                        Label {
                            text: "Cancelled At"; font.bold: true
                            Layout.preferredWidth: colW_cancelledAt
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_cancelledAt.checked
                        }
                        Label {
                            text: "Cancel Reason"; font.bold: true
                            Layout.preferredWidth: colW_cancelReason
                            visible: col_cancelReason.checked
                        }
                        Label {
                            text: "Closed At"; font.bold: true
                            Layout.preferredWidth: colW_closedAt
                            horizontalAlignment: Text.AlignHCenter
                            visible: col_closedAt.checked
                        }
                        Label {
                            text: "Ship Address"; font.bold: true
                            Layout.preferredWidth: colW_shipAddr
                            visible: col_shipAddr.checked
                        }
                        Label {
                            text: "Bill Address"; font.bold: true
                            Layout.preferredWidth: colW_billAddr
                            visible: col_billAddr.checked
                        }
                        Label {
                            text: "Discount Codes"; font.bold: true
                            Layout.preferredWidth: colW_discCodes
                            visible: col_discCodes.checked
                        }
                        Label {
                            text: "Ship Method"; font.bold: true
                            Layout.preferredWidth: colW_shipMethod
                            visible: col_shipMethod.checked
                        }
                        Label {
                            text: "Payment"; font.bold: true
                            Layout.preferredWidth: colW_payMethod
                            visible: col_payMethod.checked
                        }
                        Label {
                            text: "Landing Site"; font.bold: true
                            Layout.preferredWidth: colW_landing
                            visible: col_landing.checked
                        }
                        Label {
                            text: "Referring Site"; font.bold: true
                            Layout.preferredWidth: colW_referring
                            visible: col_referring.checked
                        }
                    }
                }

                // ── Separator ────────────────────────────────
                Rectangle {
                    width: parent.width
                    height: 1
                    color: palette.mid
                }

                // ── Orders List ──────────────────────────────
                ListView {
                    id: ordersListView
                    width: parent.width
                    height: tableFlickable.height - 33  // header + separator
                    clip: true
                    model: orderController.model
                    interactive: true

                    onContentYChanged: {
                        if (orderController.canLoadMore
                            && contentHeight > 0
                            && contentY + height >= contentHeight - 200) {
                            orderController.loadMore()
                        }
                    }

                    footer: Item {
                        width: ordersListView.width
                        height: orderController.canLoadMore ? 40 : 0
                        visible: orderController.canLoadMore
                        BusyIndicator {
                            anchors.centerIn: parent
                            running: parent.visible
                            width: 24; height: 24
                        }
                    }

                    delegate: Rectangle {
                        required property int index
                        required property string orderNumber
                        required property string customerName
                        required property string skus
                        required property string total
                        required property string shopifyStatus
                        required property string productionStatus
                        required property string createdAt
                        required property string statusColor
                        required property string email
                        required property string phone
                        required property string subtotalPrice
                        required property string totalTax
                        required property string totalDiscounts
                        required property string totalShipping
                        required property string financialStatus
                        required property string note
                        required property string tags
                        required property string sourceName
                        required property string shopifyOrderId
                        required property string displayName
                        required property string nestedAt
                        required property string cutAt
                        required property string packedAt
                        required property string syncedAt
                        required property string processedAt
                        required property string cancelledAt
                        required property string cancelReason
                        required property string closedAt
                        required property string shippingAddress
                        required property string billingAddress
                        required property string discountCodes
                        required property string shippingMethod
                        required property string paymentMethod
                        required property string landingSite
                        required property string referringSite

                        width: ordersListView.width
                        height: 36
                        color: index % 2 === 0 ? "transparent"
                            : Qt.rgba(palette.alternateBase.r,
                                      palette.alternateBase.g,
                                      palette.alternateBase.b, 0.3)

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            spacing: 4

                            Label {
                                text: orderNumber
                                Layout.preferredWidth: colW_orderNum
                                elide: Text.ElideRight
                                visible: col_orderNumber.checked
                            }
                            Label {
                                text: customerName
                                Layout.preferredWidth: colW_customer
                                elide: Text.ElideRight
                                visible: col_customer.checked
                            }
                            Label {
                                text: skus
                                Layout.preferredWidth: colW_skus
                                elide: Text.ElideRight
                                visible: col_skus.checked
                            }
                            Label {
                                text: total
                                Layout.preferredWidth: colW_total
                                horizontalAlignment: Text.AlignRight
                                visible: col_total.checked
                            }
                            Label {
                                text: shopifyStatus
                                Layout.preferredWidth: colW_shopify
                                horizontalAlignment: Text.AlignHCenter
                                color: shopifyStatus === "Fulfilled" ? "#4CAF50" : palette.windowText
                                visible: col_shopify.checked
                            }
                            Label {
                                text: productionStatus
                                Layout.preferredWidth: colW_production
                                horizontalAlignment: Text.AlignHCenter
                                font.bold: statusColor !== ""
                                color: statusColor !== "" ? statusColor : palette.windowText
                                visible: col_production.checked
                            }
                            Label {
                                text: createdAt
                                Layout.preferredWidth: colW_created
                                horizontalAlignment: Text.AlignHCenter
                                color: palette.placeholderText
                                visible: col_created.checked
                            }
                            Label {
                                text: email
                                Layout.preferredWidth: colW_email
                                elide: Text.ElideRight
                                visible: col_email.checked
                            }
                            Label {
                                text: phone
                                Layout.preferredWidth: colW_phone
                                elide: Text.ElideRight
                                visible: col_phone.checked
                            }
                            Label {
                                text: subtotalPrice
                                Layout.preferredWidth: colW_subtotal
                                horizontalAlignment: Text.AlignRight
                                visible: col_subtotal.checked
                            }
                            Label {
                                text: totalTax
                                Layout.preferredWidth: colW_tax
                                horizontalAlignment: Text.AlignRight
                                visible: col_tax.checked
                            }
                            Label {
                                text: totalDiscounts
                                Layout.preferredWidth: colW_discounts
                                horizontalAlignment: Text.AlignRight
                                visible: col_discounts.checked
                            }
                            Label {
                                text: totalShipping
                                Layout.preferredWidth: colW_shipping
                                horizontalAlignment: Text.AlignRight
                                visible: col_shippingCost.checked
                            }
                            Label {
                                text: financialStatus
                                Layout.preferredWidth: colW_financial
                                horizontalAlignment: Text.AlignHCenter
                                visible: col_financial.checked
                            }
                            Label {
                                text: note
                                Layout.preferredWidth: colW_note
                                elide: Text.ElideRight
                                visible: col_note.checked
                            }
                            Label {
                                text: tags
                                Layout.preferredWidth: colW_tags
                                elide: Text.ElideRight
                                visible: col_tags.checked
                            }
                            Label {
                                text: sourceName
                                Layout.preferredWidth: colW_source
                                visible: col_source.checked
                            }
                            Label {
                                text: shopifyOrderId
                                Layout.preferredWidth: colW_shopifyId
                                elide: Text.ElideRight
                                visible: col_shopifyId.checked
                            }
                            Label {
                                text: displayName
                                Layout.preferredWidth: colW_displayName
                                visible: col_displayName.checked
                            }
                            Label {
                                text: nestedAt
                                Layout.preferredWidth: colW_nestedAt
                                horizontalAlignment: Text.AlignHCenter
                                color: palette.placeholderText
                                visible: col_nestedAt.checked
                            }
                            Label {
                                text: cutAt
                                Layout.preferredWidth: colW_cutAt
                                horizontalAlignment: Text.AlignHCenter
                                color: palette.placeholderText
                                visible: col_cutAt.checked
                            }
                            Label {
                                text: packedAt
                                Layout.preferredWidth: colW_packedAt
                                horizontalAlignment: Text.AlignHCenter
                                color: palette.placeholderText
                                visible: col_packedAt.checked
                            }
                            Label {
                                text: syncedAt
                                Layout.preferredWidth: colW_syncedAt
                                horizontalAlignment: Text.AlignHCenter
                                color: palette.placeholderText
                                visible: col_syncedAt.checked
                            }
                            Label {
                                text: processedAt
                                Layout.preferredWidth: colW_processedAt
                                horizontalAlignment: Text.AlignHCenter
                                color: palette.placeholderText
                                visible: col_processedAt.checked
                            }
                            Label {
                                text: cancelledAt
                                Layout.preferredWidth: colW_cancelledAt
                                horizontalAlignment: Text.AlignHCenter
                                color: palette.placeholderText
                                visible: col_cancelledAt.checked
                            }
                            Label {
                                text: cancelReason
                                Layout.preferredWidth: colW_cancelReason
                                elide: Text.ElideRight
                                visible: col_cancelReason.checked
                            }
                            Label {
                                text: closedAt
                                Layout.preferredWidth: colW_closedAt
                                horizontalAlignment: Text.AlignHCenter
                                color: palette.placeholderText
                                visible: col_closedAt.checked
                            }
                            Label {
                                text: shippingAddress
                                Layout.preferredWidth: colW_shipAddr
                                elide: Text.ElideRight
                                visible: col_shipAddr.checked
                            }
                            Label {
                                text: billingAddress
                                Layout.preferredWidth: colW_billAddr
                                elide: Text.ElideRight
                                visible: col_billAddr.checked
                            }
                            Label {
                                text: discountCodes
                                Layout.preferredWidth: colW_discCodes
                                elide: Text.ElideRight
                                visible: col_discCodes.checked
                            }
                            Label {
                                text: shippingMethod
                                Layout.preferredWidth: colW_shipMethod
                                elide: Text.ElideRight
                                visible: col_shipMethod.checked
                            }
                            Label {
                                text: paymentMethod
                                Layout.preferredWidth: colW_payMethod
                                elide: Text.ElideRight
                                visible: col_payMethod.checked
                            }
                            Label {
                                text: landingSite
                                Layout.preferredWidth: colW_landing
                                elide: Text.ElideRight
                                visible: col_landing.checked
                            }
                            Label {
                                text: referringSite
                                Layout.preferredWidth: colW_referring
                                elide: Text.ElideRight
                                visible: col_referring.checked
                            }
                        }
                    }

                    // Empty state
                    Label {
                        anchors.centerIn: parent
                        visible: ordersListView.count === 0
                        text: appController.connectionOk
                              ? "No orders found"
                              : "Not connected to server"
                        color: palette.placeholderText
                        font.pixelSize: 14
                    }
                }
            }

            ScrollBar.horizontal: ScrollBar {
                policy: tableFlickable.contentWidth > tableFlickable.width
                        ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
            }
        }

        // ── Summary ────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 4

            Label {
                text: {
                    var loaded = orderController.orderCount
                    var total = orderController.totalCount
                    if (total === 0) return "No orders"
                    if (loaded >= total) return total + " orders"
                    return loaded + " of " + total + " orders"
                }
                color: palette.placeholderText
            }

            Item { Layout.fillWidth: true }
        }
    }
}
