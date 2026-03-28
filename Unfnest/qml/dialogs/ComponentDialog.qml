import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

Dialog {
    id: componentDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 400

    property bool isEdit: false
    property int editComponentId: -1
    property string editName: ""
    property string editDxfFilename: ""
    property bool editVariablePockets: false
    property string editMatingRole: "neutral"
    property string _dxfFilename: ""

    title: isEdit ? "Edit Component" : "Add New Component"

    standardButtons: Dialog.Ok | Dialog.Cancel

    ColumnLayout {
        width: componentDialog.availableWidth
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label { text: "Component Name:"; Layout.preferredWidth: 120 }
            TextField {
                id: nameField
                Layout.fillWidth: true
                placeholderText: "e.g. Side Table Leg"
                text: editName
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label { text: "DXF File:"; Layout.preferredWidth: 120 }
            Label {
                id: dxfLabel
                Layout.fillWidth: true
                text: componentDialog._dxfFilename || "No file selected"
                elide: Text.ElideMiddle
                color: componentDialog._dxfFilename ? palette.windowText : palette.placeholderText
            }
            Button {
                text: "Import..."
                onClicked: fileDialog.open()
            }
        }

        CheckBox {
            id: variablePocketsCheck
            text: "Variable pocket width"
            visible: false
            checked: editVariablePockets
            Layout.leftMargin: 128
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label { text: "Mating Role:"; Layout.preferredWidth: 120 }
            ComboBox {
                id: matingRoleCombo
                Layout.fillWidth: true
                model: ["neutral", "tab", "receiver"]
                currentIndex: {
                    if (editMatingRole === "tab") return 1
                    if (editMatingRole === "receiver") return 2
                    return 0
                }
            }
        }

    }

    onOpened: {
        if (isEdit) {
            nameField.text = editName
            _dxfFilename = editDxfFilename
            variablePocketsCheck.visible = componentController.dxfHasPockets(_dxfFilename)
            variablePocketsCheck.checked = editVariablePockets
            matingRoleCombo.currentIndex = editMatingRole === "tab" ? 1 : editMatingRole === "receiver" ? 2 : 0
        } else {
            nameField.text = ""
            _dxfFilename = ""
            variablePocketsCheck.checked = false
            variablePocketsCheck.visible = false
            matingRoleCombo.currentIndex = 0
        }
    }

    onAccepted: {
        let name = nameField.text.trim()
        let dxf = _dxfFilename
        if (!name) return
        if (!dxf) return

        let role = ["neutral", "tab", "receiver"][matingRoleCombo.currentIndex]
        if (isEdit) {
            componentController.updateComponent(editComponentId, name, dxf, variablePocketsCheck.checked, role)
        } else {
            componentController.addComponent(name, dxf, variablePocketsCheck.checked, role)
        }
    }

    function openForAdd() {
        isEdit = false
        editComponentId = -1
        editName = ""
        editDxfFilename = ""
        editVariablePockets = false
        editMatingRole = "neutral"
        open()
    }

    function openForEdit(row) {
        let compId = componentController.componentIdAtRow(row)
        let data = componentController.getComponentData(compId)
        if (!data) return

        isEdit = true
        editComponentId = compId
        editName = data.name
        editDxfFilename = data.dxf_filename
        editVariablePockets = data.variable_pockets
        editMatingRole = data.mating_role || "neutral"
        open()
    }

    FileDialog {
        id: fileDialog
        title: "Import DXF File"
        nameFilters: ["DXF Files (*.dxf)", "All Files (*)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            let filePath = selectedFile
            componentController.importDxfFile(filePath)
            // Extract filename from path
            let parts = filePath.toString().split("/")
            let filename = parts[parts.length - 1]
            _dxfFilename = filename
            variablePocketsCheck.visible = componentController.dxfHasPockets(filename)
            if (!variablePocketsCheck.visible)
                variablePocketsCheck.checked = false
        }
    }
}
