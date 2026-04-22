import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Unfnest 1.0

// Editor for a manual nest. Declared as its own top-level ApplicationWindow
// so it can be moved, resized, and closed independently of the main Unfnest
// window. Opens in response to editorController.visible going true.
ApplicationWindow {
    id: editorWindow
    title: editorController.windowTitle
    width: 1100
    height: 760
    minimumWidth: 900
    minimumHeight: 600
    visible: editorController.visible
    onClosing: (close) => editorController.close()

    // Dark mode mirrors the parent app — we can reuse the same palette trick
    readonly property bool darkMode: {
        let bg = palette.window
        let lum = (0.299 * bg.r + 0.587 * bg.g + 0.114 * bg.b)
        return lum < 0.5
    }

    // R key rotates the placement ghost. ApplicationShortcut so text
    // fields (Name / sheet-dim spinboxes) can't swallow it when they
    // happen to have keyboard focus.
    Shortcut {
        sequence: "R"
        context: Qt.ApplicationShortcut
        autoRepeat: false
        enabled: editorController.visible && editorController.ghostActive
        onActivated: editorController.rotateGhost()
    }
    // Escape cancels placement mode
    Shortcut {
        sequence: "Esc"
        context: Qt.ApplicationShortcut
        autoRepeat: false
        enabled: editorController.visible && editorController.ghostActive
        onActivated: editorController.cancelPlacement()
    }

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12

            Label { text: "Name:" }
            TextField {
                id: nameField
                Layout.preferredWidth: 260
                placeholderText: "e.g. Bench set — 1 unit"
                text: editorController.name
                onEditingFinished: editorController.setName(text)
                onAccepted: editorWindow.contentItem.forceActiveFocus()
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "Save"
                enabled: editorController.isSaveEnabled
                onClicked: editorController.save()
            }
            Button {
                text: "Cancel"
                onClicked: editorController.close()
            }
        }
    }

    // Main layout: canvas on the left, right rail with metadata + library
    RowLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 10

        // ---------------------------------------------------------------
        // Canvas + sheet navigator. Navigation and add/remove-sheet are
        // placeholders until multi-sheet editing ships.
        // ---------------------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8

            // Mating-integrity warning banner — yellow advisory, non-blocking.
            Rectangle {
                Layout.fillWidth: true
                visible: editorController.matingWarnings.length > 0
                color: editorWindow.darkMode ? "#5a4920" : "#fff3cd"
                border.color: editorWindow.darkMode ? "#8a7030" : "#d4a017"
                border.width: 1
                radius: 4
                implicitHeight: warningColumn.implicitHeight + 16
                ColumnLayout {
                    id: warningColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 8
                    spacing: 4
                    Label {
                        text: "⚠ Joinery warning"
                        font.bold: true
                        color: editorWindow.darkMode ? "#f0d080" : "#8a6508"
                    }
                    Repeater {
                        model: editorController.matingWarnings
                        Label {
                            text: "• " + modelData
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                            color: editorWindow.darkMode ? "#ddd" : "#5a4200"
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: editorWindow.darkMode ? "#222" : "#f0f0f0"
                border.color: editorWindow.darkMode ? "#444" : "#bbb"
                border.width: 1

                ManualNestCanvasItem {
                    id: canvas
                    anchors.fill: parent
                    darkMode: editorWindow.darkMode
                    sheetWidth: editorController.sheetWidth
                    sheetHeight: editorController.sheetHeight
                    edgeMargin: editorController.edgeMargin
                    placements: editorController.placements
                    ghostActive: editorController.ghostActive
                    ghostValid: editorController.ghostValid
                    ghostX: editorController.ghostX
                    ghostY: editorController.ghostY
                    ghostBboxW: editorController.ghostBboxW
                    ghostBboxH: editorController.ghostBboxH
                    ghostRotation: editorController.ghostRotation
                    ghostPolygon: editorController.ghostPolygon
                    ghostPocketPolygons: editorController.ghostPocketPolygons
                }

                // Hover + click translate pixel coords into inches for the
                // controller. Tolerant of the canvas scale being zero during
                // initial layout.
                MouseArea {
                    anchors.fill: canvas
                    hoverEnabled: editorController.ghostActive
                    acceptedButtons: Qt.LeftButton | Qt.RightButton

                    function pixelToSheet(mx, my) {
                        let s = canvas.sheetScale
                        if (s <= 0) return null
                        // Canvas draws lower-left anchored; MouseArea reports
                        // (mx, my) with origin at top-left and y growing down.
                        let xi = (mx - canvas.offsetX) / s
                        let yi = editorController.sheetHeight - (my - canvas.offsetY) / s
                        // Align the part's lower-left to cursor so the ghost
                        // hugs the cursor rather than floating centred above it
                        let gw = editorController.ghostBboxW
                        let gh = editorController.ghostBboxH
                        return { x: xi - gw / 2, y: yi - gh / 2 }
                    }

                    onPositionChanged: function(mouse) {
                        if (!editorController.ghostActive) return
                        let p = pixelToSheet(mouse.x, mouse.y)
                        if (p !== null) editorController.updateGhostPosition(p.x, p.y)
                    }
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.RightButton) {
                            editorController.cancelPlacement()
                            mouse.accepted = true
                            return
                        }
                        if (editorController.ghostActive) {
                            editorController.commitPlacement()
                        }
                    }
                }

                // Overlay instructions when in placement mode
                Label {
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.topMargin: 8
                    visible: editorController.ghostActive
                    color: editorWindow.darkMode ? "#ddd" : "#333"
                    text: "Click to place  ·  R to rotate  ·  Right-click / Esc to cancel"
                    padding: 6
                    background: Rectangle {
                        color: editorWindow.darkMode ? "#2a2a2aAA" : "#ffffffCC"
                        radius: 4
                        border.color: editorWindow.darkMode ? "#555" : "#aaa"
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: editorController.library.length === 0
                    color: editorWindow.darkMode ? "#888" : "#666"
                    text: "Use \"Add Products\" on the right to populate the part library."
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            // Sheet navigator
            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: "‹ Prev sheet"
                    enabled: editorController.canGoPrevSheet
                    onClicked: editorController.gotoPrevSheet()
                }
                Label {
                    Layout.fillWidth: true
                    text: "Sheet " + (editorController.currentSheetIndex + 1)
                        + " of " + editorController.sheetCount
                    horizontalAlignment: Text.AlignHCenter
                }
                Button {
                    text: "Next sheet ›"
                    enabled: editorController.canGoNextSheet
                    onClicked: editorController.gotoNextSheet()
                }
                Button {
                    text: "+ Add Sheet"
                    onClicked: editorController.addSheet()
                }
                Button {
                    text: "− Remove Sheet"
                    enabled: editorController.canRemoveSheet
                    onClicked: removeSheetConfirm.open()
                }
            }
        }

        // ---------------------------------------------------------------
        // Right rail: sheet metadata + library + part list
        // ---------------------------------------------------------------
        ColumnLayout {
            Layout.preferredWidth: 320
            Layout.fillHeight: true
            spacing: 10

            GroupBox {
                title: "Sheet"
                Layout.fillWidth: true
                GridLayout {
                    anchors.fill: parent
                    columns: 2
                    columnSpacing: 6
                    rowSpacing: 4

                    Label { text: "Width (in):" }
                    SpinBox {
                        id: widthSpin
                        from: 12; to: 240; editable: true
                        value: Math.round(editorController.sheetWidth)
                        onValueModified: editorController.setSheetDimensions(
                            value, editorController.sheetHeight,
                            editorController.partSpacing, editorController.edgeMargin)
                        Layout.fillWidth: true
                        Keys.onReturnPressed: editorWindow.contentItem.forceActiveFocus()
                        Keys.onEnterPressed: editorWindow.contentItem.forceActiveFocus()
                    }
                    Label { text: "Height (in):" }
                    SpinBox {
                        id: heightSpin
                        from: 12; to: 240; editable: true
                        value: Math.round(editorController.sheetHeight)
                        onValueModified: editorController.setSheetDimensions(
                            editorController.sheetWidth, value,
                            editorController.partSpacing, editorController.edgeMargin)
                        Layout.fillWidth: true
                        Keys.onReturnPressed: editorWindow.contentItem.forceActiveFocus()
                        Keys.onEnterPressed: editorWindow.contentItem.forceActiveFocus()
                    }
                    Label { text: "Part spacing:" }
                    TextField {
                        id: spacingField
                        text: editorController.partSpacing.toFixed(3)
                        Layout.fillWidth: true
                        validator: DoubleValidator { bottom: 0.0; top: 10.0; decimals: 3 }
                        onEditingFinished: {
                            let v = parseFloat(text)
                            if (!isNaN(v) && v >= 0) {
                                editorController.setSheetDimensions(
                                    editorController.sheetWidth, editorController.sheetHeight,
                                    v, editorController.edgeMargin)
                            }
                        }
                        onAccepted: editorWindow.contentItem.forceActiveFocus()
                    }
                    Label { text: "Edge margin:" }
                    TextField {
                        id: marginField
                        text: editorController.edgeMargin.toFixed(3)
                        Layout.fillWidth: true
                        validator: DoubleValidator { bottom: 0.0; top: 10.0; decimals: 3 }
                        onEditingFinished: {
                            let v = parseFloat(text)
                            if (!isNaN(v) && v >= 0) {
                                editorController.setSheetDimensions(
                                    editorController.sheetWidth, editorController.sheetHeight,
                                    editorController.partSpacing, v)
                            }
                        }
                        onAccepted: editorWindow.contentItem.forceActiveFocus()
                    }
                }
            }

            GroupBox {
                title: "Parts to place"
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 6

                    Button {
                        text: "+ Add Products"
                        Layout.fillWidth: true
                        onClicked: addProductsDialog.openPicker()
                    }

                    ListView {
                        id: libraryList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: editorController.library
                        spacing: 2

                        delegate: Rectangle {
                            width: libraryList.width
                            height: 44
                            // Placement-mode highlight must match BOTH the
                            // component id and the product SKU — two products
                            // sharing an underlying component would otherwise
                            // both light up.
                            color: editorController.ghostActive
                                && editorController.ghostComponentId === modelData.component_id
                                && editorController.ghostProductSku === modelData.product_sku
                                ? (editorWindow.darkMode ? "#3f5a2a" : "#d4edda")
                                : (index % 2 === 0
                                    ? (editorWindow.darkMode ? "#2d2d2d" : "#ffffff")
                                    : (editorWindow.darkMode ? "#333333" : "#f8f8f8"))
                            border.color: editorWindow.darkMode ? "#444" : "#ddd"

                            MouseArea {
                                anchors.fill: parent
                                enabled: modelData.placed < modelData.needed
                                onClicked: editorController.startPlacement(
                                    modelData.component_id, modelData.product_sku)
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 8

                                DXFPreviewItem {
                                    Layout.preferredWidth: 44
                                    Layout.preferredHeight: 32
                                    dxfFilename: modelData.dxf_filename || ""
                                    darkMode: editorWindow.darkMode
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    Label {
                                        text: modelData.component_name
                                        font.bold: true
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    Label {
                                        text: modelData.product_sku
                                        font.pixelSize: 10
                                        color: editorWindow.darkMode ? "#aaa" : "#666"
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                }
                                Label {
                                    text: (modelData.needed - modelData.placed)
                                        + " / " + modelData.needed
                                    horizontalAlignment: Text.AlignRight
                                    Layout.preferredWidth: 60
                                    color: modelData.placed >= modelData.needed
                                        ? (editorWindow.darkMode ? "#6aaf6a" : "#2a8a2a")
                                        : (editorWindow.darkMode ? "#ddd" : "#333")
                                }
                            }
                        }
                    }
                }
            }

            GroupBox {
                title: "Placed (" + editorController.placements.length + ")"
                Layout.fillWidth: true
                Layout.preferredHeight: 180

                ListView {
                    id: placedList
                    anchors.fill: parent
                    clip: true
                    model: editorController.placements
                    spacing: 2

                    delegate: Rectangle {
                        width: placedList.width
                        height: 28
                        color: index % 2 === 0
                            ? (editorWindow.darkMode ? "#2d2d2d" : "#ffffff")
                            : (editorWindow.darkMode ? "#333333" : "#f8f8f8")
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            anchors.rightMargin: 4

                            Label {
                                text: modelData.component_name
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Label {
                                text: "@ (" + modelData.x.toFixed(1)
                                    + ", " + modelData.y.toFixed(1) + ")"
                                color: editorWindow.darkMode ? "#aaa" : "#666"
                                font.pixelSize: 10
                            }
                            ToolButton {
                                text: "✕"
                                onClicked: editorController.removePlacement(index)
                            }
                        }
                    }

                    Label {
                        anchors.centerIn: parent
                        visible: placedList.count === 0
                        text: "No parts placed yet."
                        color: editorWindow.darkMode ? "#888" : "#999"
                    }
                }
            }
        }
    }

    // Click anywhere in the window to release focus from text fields and
    // spinboxes — matches the main Unfnest window's behaviour so values
    // commit as soon as the operator moves on. `mouse.accepted = false`
    // lets the click also reach whatever was under it (buttons, list rows,
    // canvas) so this is purely additive. Declared after the RowLayout so
    // it gets the click first in z-order.
    MouseArea {
        anchors.fill: parent
        onPressed: function(mouse) {
            editorWindow.contentItem.forceActiveFocus()
            mouse.accepted = false
        }
    }

    // Error popup for editor-controller operationFailed signals
    Dialog {
        id: editorError
        title: "Can't do that"
        modal: true
        anchors.centerIn: Overlay.overlay
        standardButtons: Dialog.Ok
        property alias text: editorErrorLabel.text
        Label {
            id: editorErrorLabel
            wrapMode: Text.WordWrap
            width: parent.width
        }
    }

    AddProductsDialog {
        id: addProductsDialog
        onProductsSelected: function(entries) {
            if (entries && entries.length > 0)
                editorController.addProducts(entries)
        }
    }

    Dialog {
        id: removeSheetConfirm
        title: "Remove Sheet"
        modal: true
        anchors.centerIn: Overlay.overlay
        standardButtons: Dialog.Yes | Dialog.No
        Label {
            text: "Remove this sheet? Any parts placed on it will go back into the library."
            wrapMode: Text.WordWrap
            width: parent.width
        }
        onAccepted: editorController.removeCurrentSheet()
    }

    Connections {
        target: editorController
        function onOperationFailed(msg) {
            editorError.text = msg
            editorError.open()
        }
    }
}
