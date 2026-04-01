import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: settingsDialog
    title: "Settings"
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 550
    height: 500

    property bool isMetric: false
    readonly property real inchToMm: 25.4

    standardButtons: Dialog.Ok | Dialog.Cancel | Dialog.RestoreDefaults

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabBar {
            id: settingsTabBar
            Layout.fillWidth: true

            TabButton { text: "General" }
            TabButton { text: "Machines" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: settingsTabBar.currentIndex

            // ==================== General Tab ====================
            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.topMargin: 12
                    spacing: 12

                    // Units toggle
                    RowLayout {
                        spacing: 8
                        Label { text: "Units:" }
                        ButtonGroup { id: unitGroup }
                        Button {
                            id: imperialBtn
                            text: "Imperial (in)"
                            checkable: true
                            checked: !isMetric
                            ButtonGroup.group: unitGroup
                            onClicked: setUnits(false)
                        }
                        Button {
                            id: metricBtn
                            text: "Metric (mm)"
                            checkable: true
                            checked: isMetric
                            ButtonGroup.group: unitGroup
                            onClicked: setUnits(true)
                        }
                        Item { Layout.fillWidth: true }
                    }

                    // Sheet Size
                    GroupBox {
                        title: "Sheet Size"
                        Layout.fillWidth: true
                        GridLayout {
                            columns: 2
                            anchors.fill: parent
                            columnSpacing: 8
                            rowSpacing: 8

                            Label { text: "Width:" }
                            SpinBox {
                                id: widthSpin
                                from: isMetric ? 2500 : 100
                                to: isMetric ? 800000 : 30000
                                stepSize: isMetric ? 1000 : 100
                                editable: true
                                Layout.fillWidth: true
                                textFromValue: function(value) { return (value / 100).toFixed(2) + (isMetric ? " mm" : " in") }
                                valueFromText: function(text) { return Math.round(parseFloat(text) * 100) }
                            }

                            Label { text: "Height:" }
                            SpinBox {
                                id: heightSpin
                                from: isMetric ? 2500 : 100
                                to: isMetric ? 800000 : 30000
                                stepSize: isMetric ? 1000 : 100
                                editable: true
                                Layout.fillWidth: true
                                textFromValue: function(value) { return (value / 100).toFixed(2) + (isMetric ? " mm" : " in") }
                                valueFromText: function(text) { return Math.round(parseFloat(text) * 100) }
                            }
                        }
                    }

                    // Spacing
                    GroupBox {
                        title: "Spacing"
                        Layout.fillWidth: true
                        GridLayout {
                            columns: 2
                            anchors.fill: parent
                            columnSpacing: 8
                            rowSpacing: 4

                            Label { text: "Part Spacing:" }
                            SpinBox {
                                id: spacingSpin
                                from: 0
                                to: isMetric ? 254000 : 10000
                                stepSize: isMetric ? 500 : 125
                                editable: true
                                Layout.fillWidth: true
                                textFromValue: function(value) { return (value / 1000).toFixed(3) + (isMetric ? " mm" : " in") }
                                valueFromText: function(text) { return Math.round(parseFloat(text) * 1000) }
                            }

                            Label { text: "" }
                            Label {
                                text: "(Distance between parts — typically your bit diameter)"
                                font.pixelSize: 10
                                opacity: 0.6
                            }

                            Label { text: "Edge Margin:" }
                            SpinBox {
                                id: marginSpin
                                from: 0
                                to: isMetric ? 254000 : 10000
                                stepSize: isMetric ? 500 : 125
                                editable: true
                                Layout.fillWidth: true
                                textFromValue: function(value) { return (value / 1000).toFixed(3) + (isMetric ? " mm" : " in") }
                                valueFromText: function(text) { return Math.round(parseFloat(text) * 1000) }
                            }

                            Label { text: "" }
                            Label {
                                text: "(Distance from sheet edge — like printer margins)"
                                font.pixelSize: 10
                                opacity: 0.6
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }
                }
            }

            // ==================== Machines Tab ====================
            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.topMargin: 12
                    spacing: 8

                    Label {
                        text: "Registered CNC machines. Active machines will receive nested sheets."
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        opacity: 0.7
                    }

                    // Machine list
                    ListView {
                        id: machineListView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: machineController.getModel()

                        header: Rectangle {
                            width: machineListView.width
                            height: 30
                            color: root.darkMode ? "#3a3a3a" : "#e8e8e8"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                Label { text: "Machine Name"; Layout.fillWidth: true; font.bold: true }
                                Label { text: "Active"; Layout.preferredWidth: 60; font.bold: true; horizontalAlignment: Text.AlignHCenter }
                                Label { text: ""; Layout.preferredWidth: 60 }
                            }
                        }

                        delegate: Rectangle {
                            id: machineDelegate
                            required property int index
                            required property int machineId
                            required property string name
                            required property bool active
                            width: machineListView.width
                            height: 36
                            color: machineDelegate.index % 2 === 0
                                ? (root.darkMode ? "#2d2d2d" : "#ffffff")
                                : (root.darkMode ? "#333333" : "#f8f8f8")

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8

                                Label {
                                    text: machineDelegate.name
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }

                                Switch {
                                    checked: machineDelegate.active
                                    Layout.preferredWidth: 60
                                    onToggled: machineController.setActive(machineDelegate.index, checked)
                                }

                                Button {
                                    text: "Delete"
                                    Layout.preferredWidth: 60
                                    onClicked: {
                                        deleteMachineIndex = machineDelegate.index
                                        deleteMachineName = machineDelegate.name
                                        deleteMachineDialog.open()
                                    }
                                }
                            }
                        }
                    }

                    // Register new machine
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        TextField {
                            id: newMachineField
                            Layout.fillWidth: true
                            placeholderText: "Machine name..."
                            onAccepted: registerBtn.clicked()
                        }

                        Button {
                            id: registerBtn
                            text: "Register"
                            enabled: newMachineField.text.trim().length > 0
                            onClicked: {
                                if (machineController.registerMachine(newMachineField.text)) {
                                    newMachineField.text = ""
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Delete confirmation dialog
    property int deleteMachineIndex: -1
    property string deleteMachineName: ""

    Dialog {
        id: deleteMachineDialog
        title: "Delete Machine"
        modal: true
        anchors.centerIn: Overlay.overlay
        standardButtons: Dialog.Yes | Dialog.No

        Label {
            text: "Delete machine '" + deleteMachineName + "'?\n\nThis cannot be undone."
            wrapMode: Text.WordWrap
        }

        onAccepted: {
            machineController.deleteMachine(deleteMachineIndex)
        }
    }

    function setUnits(metric) {
        if (metric === isMetric) return
        let factor = metric ? inchToMm : (1.0 / inchToMm)

        let w = widthSpin.value / 100.0 * factor
        let h = heightSpin.value / 100.0 * factor
        let s = spacingSpin.value / 1000.0 * factor
        let m = marginSpin.value / 1000.0 * factor

        isMetric = metric

        widthSpin.value = Math.round(w * 100)
        heightSpin.value = Math.round(h * 100)
        spacingSpin.value = Math.round(s * 1000)
        marginSpin.value = Math.round(m * 1000)
    }

    onOpened: {
        isMetric = settingsController.isMetric()
        let sw = settingsController.sheetWidth()
        let sh = settingsController.sheetHeight()
        let ps = settingsController.partSpacing()
        let em = settingsController.edgeMargin()

        if (isMetric) {
            sw *= inchToMm
            sh *= inchToMm
            ps *= inchToMm
            em *= inchToMm
        }

        widthSpin.value = Math.round(sw * 100)
        heightSpin.value = Math.round(sh * 100)
        spacingSpin.value = Math.round(ps * 1000)
        marginSpin.value = Math.round(em * 1000)

        // Refresh machines when dialog opens
        machineController.refresh()
    }

    onAccepted: {
        // Only save general settings (machines save immediately via their own controls)
        let w = widthSpin.value / 100.0
        let h = heightSpin.value / 100.0
        let s = spacingSpin.value / 1000.0
        let m = marginSpin.value / 1000.0
        settingsController.saveSettings(w, h, s, m, isMetric)
    }

    onReset: {
        isMetric = false
        widthSpin.value = 4800
        heightSpin.value = 9600
        spacingSpin.value = 750
        marginSpin.value = 750
    }
}
