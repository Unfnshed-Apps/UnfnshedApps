import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: productDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 550
    height: 500

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
    }

    // Internal component model
    ListModel {
        id: compModel
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
        compModel.remove(index)
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

        if (isEdit) {
            productController.updateProduct(sku, name, descField.text.trim(), outsourcedCheck.checked, components)
        } else {
            productController.addProduct(sku, name, descField.text.trim(), outsourcedCheck.checked, components)
        }

        productController.refresh()
        componentController.refresh()
    }

    // New component dialog (for creating components from within product dialog)
    ComponentDialog {
        id: newCompDialog
    }
}
