import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Product + quantity picker used from the Manual Nest editor. Pulls the
// product list from productController, emits a `productsSelected` signal
// with a QVariantList of {sku, qty} dicts for the rows the user set qty >= 1.
Dialog {
    id: dialog
    title: "Add Products"
    modal: true
    width: 460
    height: 520
    anchors.centerIn: Overlay.overlay
    standardButtons: Dialog.Ok | Dialog.Cancel

    // Locally-computed dark mode so this dialog can be opened from any
    // top-level window (main app or the Manual Nest editor)
    readonly property bool darkMode: {
        let bg = palette.window
        let lum = (0.299 * bg.r + 0.587 * bg.g + 0.114 * bg.b)
        return lum < 0.5
    }

    signal productsSelected(var entries)

    // quantityMap: sku -> int
    property var quantityMap: ({})

    function openPicker() {
        quantityMap = ({})
        productList.model = productController.model
        dialog.open()
    }

    onAccepted: {
        let entries = []
        for (let sku in quantityMap) {
            let q = parseInt(quantityMap[sku])
            if (!isNaN(q) && q > 0) entries.push({ sku: sku, qty: q })
        }
        productsSelected(entries)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        Label {
            text: "Pick products and the number of units you want to include:"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        ListView {
            id: productList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: productController.model

            header: Rectangle {
                width: productList.width
                height: 28
                color: dialog.darkMode ? "#3a3a3a" : "#e8e8e8"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 8
                    Label { text: "SKU"; Layout.preferredWidth: 120; font.bold: true }
                    Label { text: "Name"; Layout.fillWidth: true; font.bold: true }
                    Label { text: "Quantity"; Layout.preferredWidth: 100; font.bold: true }
                }
            }

            delegate: Rectangle {
                width: productList.width
                height: 36
                color: index % 2 === 0
                    ? (dialog.darkMode ? "#2d2d2d" : "#ffffff")
                    : (dialog.darkMode ? "#333333" : "#f8f8f8")

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 8

                    Label {
                        text: model.sku
                        Layout.preferredWidth: 120
                        elide: Text.ElideRight
                    }
                    Label {
                        text: model.name
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    SpinBox {
                        id: qtySpin
                        Layout.preferredWidth: 100
                        from: 0
                        to: 999
                        editable: true
                        value: dialog.quantityMap[model.sku] || 0

                        // Push typed text into the quantityMap on every
                        // keystroke so a quick Click-OK-without-Enter still
                        // commits the value. Without this, the text-field
                        // only commits on Enter or blur, and a fast-clicking
                        // user loses the last row they typed.
                        function commitText() {
                            if (!contentItem) return
                            let parsed = parseInt(contentItem.text)
                            if (isNaN(parsed)) parsed = 0
                            parsed = Math.max(from, Math.min(to, parsed))
                            let next = Object.assign({}, dialog.quantityMap)
                            if (parsed > 0) next[model.sku] = parsed
                            else delete next[model.sku]
                            dialog.quantityMap = next
                        }
                        onValueModified: commitText()
                        Connections {
                            target: qtySpin.contentItem
                            function onTextChanged() {
                                if (qtySpin.contentItem.activeFocus) qtySpin.commitText()
                            }
                        }
                    }
                }
            }

            ScrollBar.vertical: ScrollBar {}

            Label {
                anchors.centerIn: parent
                visible: productList.count === 0
                text: "No products available yet — add some on the Products tab first."
                color: dialog.darkMode ? "#888" : "#666"
            }
        }
    }
}
