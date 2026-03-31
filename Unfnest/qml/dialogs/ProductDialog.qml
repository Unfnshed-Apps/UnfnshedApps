import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: productDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 600
    height: 650

    property bool isEdit: false
    property string editSku: ""

    title: isEdit ? "Edit Product" : "Add New Product"

    standardButtons: Dialog.Ok | Dialog.Cancel

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        // Product info form
        GridLayout {
            columns: 2
            Layout.fillWidth: true
            columnSpacing: 8
            rowSpacing: 8

            Label { text: "SKU:" }
            TextField {
                id: skuField
                Layout.fillWidth: true
                enabled: !isEdit
            }

            Label { text: "Product Name:" }
            TextField {
                id: nameField
                Layout.fillWidth: true
            }

            Label { text: "Description:" }
            TextField {
                id: descField
                Layout.fillWidth: true
            }

            Label { text: "Outsourced:" }
            CheckBox {
                id: outsourcedCheck
                text: "Product is made externally (won't be included in nesting)"
            }
        }

        // Components section
        GroupBox {
            title: "Components"
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 4

                // Components list
                ListView {
                    id: compListView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: compModel

                    header: Rectangle {
                        width: compListView.width
                        height: 25
                        color: root.darkMode ? "#3a3a3a" : "#e8e8e8"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 4
                            anchors.rightMargin: 4
                            Label { text: "Component"; Layout.fillWidth: true; font.bold: true; color: root.darkMode ? "#e0e0e0" : "#333333" }
                            Label { text: "Role"; Layout.preferredWidth: 100; font.bold: true; color: root.darkMode ? "#e0e0e0" : "#333333" }
                            Label { text: "Qty"; Layout.preferredWidth: 40; font.bold: true; color: root.darkMode ? "#e0e0e0" : "#333333" }
                            Label { text: ""; Layout.preferredWidth: 60 }
                        }
                    }

                    delegate: Rectangle {
                        id: delegateRect
                        required property int index
                        required property string componentName
                        required property string matingRole
                        required property int quantity
                        required property int componentId
                        width: compListView.width
                        height: 30
                        color: delegateRect.index % 2 === 0
                            ? (root.darkMode ? "#2d2d2d" : "#ffffff")
                            : (root.darkMode ? "#333333" : "#f8f8f8")
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 4
                            anchors.rightMargin: 4
                            Label { text: delegateRect.componentName; Layout.fillWidth: true; elide: Text.ElideRight; color: root.darkMode ? "#e0e0e0" : "#333333" }
                            Label {
                                text: delegateRect.matingRole
                                Layout.preferredWidth: 100
                                color: root.darkMode ? "#aaaaaa" : "#666666"
                            }
                            Label { text: delegateRect.quantity; Layout.preferredWidth: 40; color: root.darkMode ? "#e0e0e0" : "#333333" }
                            Button {
                                text: "Remove"
                                Layout.preferredWidth: 60
                                onClicked: productDialog.removeComponent(delegateRect.index)
                            }
                        }
                    }
                }

                // Add existing component row
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    ComboBox {
                        id: compCombo
                        Layout.fillWidth: true
                        model: []  // populated on open
                    }

                    Label { text: "Qty:" }

                    SpinBox {
                        id: addQtySpin
                        from: 1
                        to: 999
                        editable: true
                        value: 1
                        Layout.preferredWidth: 80
                    }

                    Button {
                        text: "Add"
                        onClicked: productDialog.addExistingComponent()
                    }
                }

                Button {
                    text: "+ Create New Component..."
                    onClicked: newCompDialog.openForAdd()
                }
            }
        }

        // Mating Pairs section — visible when both tab and receiver components exist
        GroupBox {
            id: matingPairsGroup
            title: "Mating Pairs"
            Layout.fillWidth: true
            Layout.preferredHeight: 180
            visible: _hasTabComponents() && _hasReceiverComponents()

            ColumnLayout {
                anchors.fill: parent
                spacing: 4

                // Warning if tab+receiver exist but no pairs defined
                Label {
                    visible: matingPairModel.count === 0
                    text: "No mating pairs defined. Pocket depths will use default values."
                    color: "#b8860b"
                    font.italic: true
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }

                // Pairs list
                ListView {
                    id: mpListView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: matingPairModel
                    visible: matingPairModel.count > 0

                    delegate: Rectangle {
                        id: mpDelegate
                        required property int index
                        required property int pocketComponentId
                        required property int matingComponentId
                        required property int pocketIndex
                        required property real clearanceInches
                        width: mpListView.width
                        height: 28
                        color: mpDelegate.index % 2 === 0
                            ? (root.darkMode ? "#2d2d2d" : "#ffffff")
                            : (root.darkMode ? "#333333" : "#f8f8f8")
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 4
                            anchors.rightMargin: 4
                            Label {
                                text: _componentNameById(mpDelegate.matingComponentId)
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                color: root.darkMode ? "#e0e0e0" : "#333333"
                            }
                            Label {
                                text: "\u2192"
                                Layout.preferredWidth: 20
                                horizontalAlignment: Text.AlignHCenter
                                color: root.darkMode ? "#aaaaaa" : "#666666"
                            }
                            Label {
                                text: _componentNameById(mpDelegate.pocketComponentId)
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                color: root.darkMode ? "#e0e0e0" : "#333333"
                            }
                            Button {
                                text: "Remove"
                                Layout.preferredWidth: 60
                                onClicked: matingPairModel.remove(mpDelegate.index)
                            }
                        }
                    }
                }

                // Add pair row
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label { text: "Tab:"; color: root.darkMode ? "#e0e0e0" : "#333333" }
                    ComboBox {
                        id: tabCombo
                        Layout.fillWidth: true
                        model: _getTabComponentNames()
                    }

                    Label { text: "\u2192"; color: root.darkMode ? "#aaaaaa" : "#666666" }

                    Label { text: "Receiver:"; color: root.darkMode ? "#e0e0e0" : "#333333" }
                    ComboBox {
                        id: receiverCombo
                        Layout.fillWidth: true
                        model: _getReceiverComponentNames()
                    }

                    Button {
                        text: "Add"
                        onClicked: productDialog.addMatingPair()
                    }
                }
            }
        }
    }

    // Internal component model
    ListModel {
        id: compModel
    }

    // Mating pairs model
    ListModel {
        id: matingPairModel
    }

    // Data for the combo box
    property var allComponents: []

    function openForAdd() {
        isEdit = false
        editSku = ""
        skuField.text = ""
        nameField.text = ""
        descField.text = ""
        outsourcedCheck.checked = false
        compModel.clear()
        matingPairModel.clear()
        _refreshCombo()
        open()
    }

    function openForEdit(sku) {
        let data = productController.getProduct(sku)
        if (!data || !data.sku) return

        isEdit = true
        editSku = sku
        skuField.text = data.sku
        nameField.text = data.name
        descField.text = data.description
        outsourcedCheck.checked = data.outsourced

        compModel.clear()
        let comps = data.components
        for (let i = 0; i < comps.length; i++) {
            compModel.append({
                "componentId": comps[i].component_id,
                "componentName": comps[i].component_name,
                "dxfFilename": comps[i].dxf_filename,
                "quantity": comps[i].quantity,
                "matingRole": comps[i].mating_role || "neutral"
            })
        }

        matingPairModel.clear()
        let pairs = data.mating_pairs || []
        for (let j = 0; j < pairs.length; j++) {
            matingPairModel.append({
                "pocketComponentId": pairs[j].pocket_component_id,
                "matingComponentId": pairs[j].mating_component_id,
                "pocketIndex": pairs[j].pocket_index || 0,
                "clearanceInches": pairs[j].clearance_inches || 0.0079
            })
        }

        _refreshCombo()
        open()
    }

    function _refreshCombo() {
        allComponents = productController.getAllComponentDefinitions()
        let displayList = []
        for (let i = 0; i < allComponents.length; i++) {
            displayList.push(allComponents[i].name + " (" + allComponents[i].dxf_filename + ")")
        }
        compCombo.model = displayList
    }

    function addExistingComponent() {
        if (compCombo.currentIndex < 0 || allComponents.length === 0) return
        let comp = allComponents[compCombo.currentIndex]
        compModel.append({
            "componentId": comp.id,
            "componentName": comp.name,
            "dxfFilename": comp.dxf_filename,
            "quantity": addQtySpin.value,
            "matingRole": comp.mating_role || "neutral"
        })
        addQtySpin.value = 1
    }

    function removeComponent(index) {
        let removedId = compModel.get(index).componentId
        compModel.remove(index)
        // Clean up mating pairs referencing removed component
        for (let i = matingPairModel.count - 1; i >= 0; i--) {
            let mp = matingPairModel.get(i)
            if (mp.pocketComponentId === removedId || mp.matingComponentId === removedId) {
                matingPairModel.remove(i)
            }
        }
    }

    function addMatingPair() {
        let tabs = _getTabComponents()
        let receivers = _getReceiverComponents()
        if (tabCombo.currentIndex < 0 || receiverCombo.currentIndex < 0) return
        if (tabs.length === 0 || receivers.length === 0) return

        let tab = tabs[tabCombo.currentIndex]
        let receiver = receivers[receiverCombo.currentIndex]

        // Check for duplicate
        for (let i = 0; i < matingPairModel.count; i++) {
            let existing = matingPairModel.get(i)
            if (existing.pocketComponentId === receiver.componentId &&
                existing.matingComponentId === tab.componentId) {
                return  // Already exists
            }
        }

        matingPairModel.append({
            "pocketComponentId": receiver.componentId,
            "matingComponentId": tab.componentId,
            "pocketIndex": 0,
            "clearanceInches": 0.0079
        })
    }

    // Helper: get components with tab role from compModel
    function _getTabComponents() {
        let result = []
        for (let i = 0; i < compModel.count; i++) {
            let c = compModel.get(i)
            if (c.matingRole === "tab") result.push(c)
        }
        return result
    }

    function _getReceiverComponents() {
        let result = []
        for (let i = 0; i < compModel.count; i++) {
            let c = compModel.get(i)
            if (c.matingRole === "receiver") result.push(c)
        }
        return result
    }

    function _getTabComponentNames() {
        let tabs = _getTabComponents()
        let names = []
        for (let i = 0; i < tabs.length; i++) names.push(tabs[i].componentName)
        return names
    }

    function _getReceiverComponentNames() {
        let receivers = _getReceiverComponents()
        let names = []
        for (let i = 0; i < receivers.length; i++) names.push(receivers[i].componentName)
        return names
    }

    function _hasTabComponents() {
        for (let i = 0; i < compModel.count; i++) {
            if (compModel.get(i).matingRole === "tab") return true
        }
        return false
    }

    function _hasReceiverComponents() {
        for (let i = 0; i < compModel.count; i++) {
            if (compModel.get(i).matingRole === "receiver") return true
        }
        return false
    }

    function _componentNameById(id) {
        for (let i = 0; i < compModel.count; i++) {
            if (compModel.get(i).componentId === id) return compModel.get(i).componentName
        }
        return "Unknown"
    }

    onAccepted: {
        let sku = skuField.text.trim()
        let name = nameField.text.trim()
        if (!sku || !name) return
        if (compModel.count === 0) return

        let components = []
        for (let i = 0; i < compModel.count; i++) {
            let item = compModel.get(i)
            components.push([item.componentId, item.quantity])
        }

        let pairs = []
        for (let j = 0; j < matingPairModel.count; j++) {
            let mp = matingPairModel.get(j)
            pairs.push([mp.pocketComponentId, mp.matingComponentId, mp.pocketIndex, mp.clearanceInches])
        }

        if (isEdit) {
            productController.updateProduct(sku, name, descField.text.trim(), outsourcedCheck.checked, components, pairs)
        } else {
            productController.addProduct(sku, name, descField.text.trim(), outsourcedCheck.checked, components, pairs)
        }

        productController.refresh()
        componentController.refresh()
    }

    // New component dialog (for creating components from within product dialog)
    ComponentDialog {
        id: newCompDialog
    }
}
