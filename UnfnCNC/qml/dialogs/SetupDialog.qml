import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: setupDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 550
    height: 600

    property bool firstRun: true
    property bool isMetric: false

    // Internal state
    property var toolLibrary: []
    property var gcodeSettings: ({})

    title: firstRun ? "UnfnCNC Setup" : "Settings"

    // Conversion helpers
    readonly property real inchToMm: 25.4
    function toDisplay(inches) { return isMetric ? inches * inchToMm : inches }
    function toInches(display) { return isMetric ? display / inchToMm : display }
    function lenSuffix() { return isMetric ? " mm" : " in" }
    function feedSuffix() { return isMetric ? " mm/min" : " IPM" }
    function diaSuffix() { return isMetric ? " mm" : '"' }

    // SpinBox.textFromValue is not reactive to external state — it only
    // re-evaluates when `value` changes.  Nudge every unit-aware SpinBox
    // so the display text refreshes after a unit toggle.
    function refreshUnitSpinBoxes() {
        var boxes = [newToolDia,
                     cutDepthAdjustment, pocketClearance, safeZ, retractZ,
                     feedXyRough, feedXyFinish, feedZ,
                     rampAngle, endPositionOffset, endZHeight]
        for (var i = 0; i < boxes.length; i++) {
            var b = boxes[i]
            if (b) { b.value += 1; b.value -= 1 }
        }
    }
    onIsMetricChanged: refreshUnitSpinBoxes()

    onOpened: {
        isMetric = false

        // Fetch registered machines from server
        _refreshMachineList()

        if (firstRun) {
            machineLetterCombo.currentIndex = 0
            hotFolderField.text = ""
            deviceNameField.text = settingsController.suggestedDeviceName()
            apiKeyField.text = ""
            apiUrlField.text = ""
            lanIpField.text = ""
            gcodeSettings = JSON.parse(settingsController.defaultGcodeSettingsJson())
            toolLibrary = JSON.parse(settingsController.defaultToolLibraryJson())
        } else {
            let ml = settingsController.currentMachineLetter()
            _selectMachineByName(ml)
            hotFolderField.text = settingsController.currentHotFolder()
            deviceNameField.text = settingsController.currentDeviceName()
            apiKeyField.text = settingsController.currentApiKey()
            apiUrlField.text = settingsController.currentApiUrl()
            lanIpField.text = settingsController.currentLanIp()
            gcodeSettings = JSON.parse(settingsController.currentGcodeSettingsJson())
            toolLibrary = JSON.parse(settingsController.currentToolLibraryJson())
        }
        loadGcodeToSpinboxes()
        toolLibraryModel.refresh()
        refreshToolCombos()
        testStatusLabel.text = ""
    }

    function _refreshMachineList() {
        let machinesJson = settingsController.fetchMachinesJson()
        let machines = JSON.parse(machinesJson)
        machineListModel.clear()
        // Add fallback letters if server returned nothing
        if (machines.length === 0) {
            let letters = settingsController.machineLetters()
            for (let i = 0; i < letters.length; i++) {
                machineListModel.append({"name": letters[i]})
            }
        } else {
            for (let j = 0; j < machines.length; j++) {
                machineListModel.append({"name": machines[j].name})
            }
        }
    }

    function _selectMachineByName(name) {
        for (let i = 0; i < machineListModel.count; i++) {
            if (machineListModel.get(i).name === name) {
                machineLetterCombo.currentIndex = i
                return
            }
        }
        machineLetterCombo.currentIndex = 0
    }

    function loadGcodeToSpinboxes() {
        let g = gcodeSettings
        spindleRpm.value = g.spindle_rpm || 18000
        feedXyRough.value = g.feed_xy_rough || 650
        feedXyFinish.value = g.feed_xy_finish || 350
        feedZ.value = g.feed_z || 60
        cutDepthAdjustment.realValue = g.cut_depth_adjustment || 0.0
        roughingPct.value = g.roughing_pct || 80
        zeroFromCombo.currentIndex = (g.zero_from === "top") ? 1 : 0
        pocketClearance.realValue = g.pocket_clearance || 0.0079
        safeZ.realValue = g.safe_z || 0.2004
        retractZ.realValue = g.retract_z || 0.1969
        endPositionOffset.realValue = g.end_position_offset || 3.0
        endZHeight.realValue = g.end_z_height || 2.0
        rampAngle.realValue = g.ramp_angle || 5.0
    }

    function collectGcodeFromSpinboxes() {
        return {
            spindle_rpm: spindleRpm.value,
            feed_xy_rough: feedXyRough.value,
            feed_xy_finish: feedXyFinish.value,
            feed_z: feedZ.value,
            cut_depth_adjustment: cutDepthAdjustment.realValue,
            roughing_pct: roughingPct.value,
            zero_from: zeroFromCombo.currentIndex === 1 ? "top" : "spoilboard",
            pocket_clearance: pocketClearance.realValue,
            safe_z: safeZ.realValue,
            retract_z: retractZ.realValue,
            end_position_offset: endPositionOffset.realValue,
            end_z_height: endZHeight.realValue,
            ramp_angle: rampAngle.realValue,
            outline_tool: outlineToolCombo.currentValue ?? 5,
            pocket_tool: pocketToolCombo.currentValue ?? 5,
        }
    }

    function refreshToolCombos() {
        let prevOutline = outlineToolCombo.currentValue
        let prevPocket = pocketToolCombo.currentValue

        outlineToolModel.clear()
        pocketToolModel.clear()
        outlineToolModel.append({text: "(Not assigned)", value: 0})
        pocketToolModel.append({text: "(Not assigned)", value: 0})

        let sorted = toolLibrary.slice().sort((a, b) => a.number - b.number)
        for (let t of sorted) {
            let dia = toDisplay(t.diameter).toFixed(isMetric ? 2 : 3) + diaSuffix()
            let display = "T" + t.number + ": " + t.name + " (" + dia + " " + t.type + ")"
            outlineToolModel.append({text: display, value: t.number})
            pocketToolModel.append({text: display, value: t.number})
        }

        // Restore selection
        for (let i = 0; i < outlineToolModel.count; i++) {
            if (outlineToolModel.get(i).value === prevOutline)
                outlineToolCombo.currentIndex = i
        }
        for (let i = 0; i < pocketToolModel.count; i++) {
            if (pocketToolModel.get(i).value === prevPocket)
                pocketToolCombo.currentIndex = i
        }
    }

    // ==================== Content ====================

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        // Welcome header (first run only)
        Label {
            visible: firstRun
            text: "Welcome to UnfnCNC!"
            font.pixelSize: 16
            font.bold: true
        }
        Label {
            visible: firstRun
            text: "Select your machine letter and hot folder path.\nThe server connection will be detected automatically."
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        Rectangle { visible: firstRun; Layout.fillWidth: true; height: 1; color: palette.mid }

        // Units toggle
        RowLayout {
            spacing: 8
            Label { text: "Units:" }
            Button {
                text: "Imperial (in)"
                checkable: true
                checked: !isMetric
                onClicked: isMetric = false
            }
            Button {
                text: "Metric (mm)"
                checkable: true
                checked: isMetric
                onClicked: isMetric = true
            }
            Item { Layout.fillWidth: true }
        }

        // Tab bar
        TabBar {
            id: tabBar
            Layout.fillWidth: true
            TabButton { text: "Machine" }
            TabButton { text: "Tool Library" }
            TabButton { text: "G-Code" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            // ==================== Tab 1: Machine ====================
            ScrollView {
                ColumnLayout {
                    width: parent.width
                    spacing: 8

                    GroupBox {
                        title: "Machine"
                        Layout.fillWidth: true
                        GridLayout {
                            columns: 2
                            anchors.fill: parent
                            columnSpacing: 8
                            rowSpacing: 6

                            Label { text: "Machine:" }
                            ComboBox {
                                id: machineLetterCombo
                                model: ListModel { id: machineListModel }
                                textRole: "name"
                                Layout.preferredWidth: 200
                            }
                            Label { text: "" }
                            Label {
                                text: machineListModel.count === 0 ? "No machines registered. Add machines in Unfnest Settings." : ""
                                font.pixelSize: 10
                                opacity: 0.6
                                visible: machineListModel.count === 0
                            }

                            Label { text: "Hot Folder:" }
                            RowLayout {
                                Layout.fillWidth: true
                                TextField {
                                    id: hotFolderField
                                    Layout.fillWidth: true
                                    placeholderText: "/path/to/cnc/hot-folder"
                                }
                                Button {
                                    text: "Browse..."
                                    onClicked: {
                                        let f = settingsController.browseHotFolder()
                                        if (f) hotFolderField.text = f
                                    }
                                }
                            }

                            Label { text: "" }
                            Label { text: "CNC controller watches this folder for .tap files"; font.pixelSize: 11; opacity: 0.6 }
                        }
                    }

                    GroupBox {
                        title: "Connection"
                        Layout.fillWidth: true
                        GridLayout {
                            columns: 2
                            anchors.fill: parent
                            columnSpacing: 8
                            rowSpacing: 6

                            Label { text: "Device Name:" }
                            TextField {
                                id: deviceNameField
                                Layout.fillWidth: true
                                placeholderText: "e.g., CNC-Shop-1"
                            }

                            Label { text: "API Key:" }
                            TextField {
                                id: apiKeyField
                                Layout.fillWidth: true
                                placeholderText: "Enter your API key"
                                echoMode: showKeyCheck.checked ? TextInput.Normal : TextInput.Password
                            }

                            Label { text: "" }
                            CheckBox { id: showKeyCheck; text: "Show key" }
                        }
                    }

                    GroupBox {
                        title: "Advanced Settings"
                        Layout.fillWidth: true
                        visible: !firstRun
                        GridLayout {
                            columns: 2
                            anchors.fill: parent
                            columnSpacing: 8
                            rowSpacing: 6

                            Label { text: "LAN Server IP:" }
                            TextField { id: lanIpField; Layout.fillWidth: true; placeholderText: "e.g., 192.168.0.242" }

                            Label { text: "Server URL:" }
                            TextField { id: apiUrlField; Layout.fillWidth: true; placeholderText: "Leave blank for auto-detect" }
                        }
                    }

                    RowLayout {
                        spacing: 8
                        Button {
                            text: "Test Connection"
                            onClicked: settingsController.testConnection()
                        }
                        Label {
                            id: testStatusLabel
                            text: settingsController.testStatus
                            color: settingsController.testStatusOk ? "green" : (settingsController.testStatus !== "" ? "red" : palette.windowText)
                        }
                    }
                }
            }

            // ==================== Tab 2: Tool Library ====================
            ColumnLayout {
                spacing: 8

                GroupBox {
                    title: "Tool Library"
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 4

                        // Tool table header
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Tool #"; font.bold: true; Layout.preferredWidth: 50 }
                            Label { text: "Name"; font.bold: true; Layout.fillWidth: true }
                            Label { text: "Diameter"; font.bold: true; Layout.preferredWidth: 80 }
                            Label { text: "Type"; font.bold: true; Layout.preferredWidth: 90 }
                            Item { Layout.preferredWidth: 70 }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: palette.mid }

                        ListView {
                            id: toolListView
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: ListModel { id: toolLibraryModel }

                            delegate: RowLayout {
                                width: toolListView.width
                                required property int index
                                required property int toolNumber
                                required property string toolName
                                required property real toolDiameter
                                required property string toolType

                                Label { text: "T" + toolNumber; Layout.preferredWidth: 50 }
                                Label { text: toolName; Layout.fillWidth: true; elide: Text.ElideRight }
                                Label {
                                    text: toDisplay(toolDiameter).toFixed(isMetric ? 2 : 4) + diaSuffix()
                                    Layout.preferredWidth: 80
                                }
                                Label { text: toolType; Layout.preferredWidth: 90 }
                                Button {
                                    text: "Remove"
                                    Layout.preferredWidth: 70
                                    onClicked: {
                                        toolLibrary.splice(index, 1)
                                        toolLibraryModel.refresh()
                                        refreshToolCombos()
                                    }
                                }
                            }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: palette.mid }

                        // Add tool row
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            SpinBox { id: newToolNum; from: 1; to: 99; value: 1; Layout.preferredWidth: 80 }
                            TextField { id: newToolName; placeholderText: "Tool name"; Layout.fillWidth: true }
                            SpinBox {
                                id: newToolDia
                                from: 63; to: 2000; stepSize: 63
                                value: 375
                                Layout.preferredWidth: 110
                                property real realValue: value / 10000.0
                                onRealValueChanged: value = Math.round(realValue * 10000)
                                textFromValue: function(v) { return toDisplay(v / 10000.0).toFixed(isMetric ? 2 : 4) + diaSuffix() }
                            }
                            ComboBox {
                                id: newToolType
                                model: ["End Mill", "Down Cut", "Up Cut", "Compression", "Ball Nose", "V-Bit", "Drill", "Other"]
                                Layout.preferredWidth: 110
                            }
                            Button {
                                text: "Add"
                                onClicked: {
                                    let name = newToolName.text.trim()
                                    if (!name) return
                                    let num = newToolNum.value
                                    for (let t of toolLibrary) {
                                        if (t.number === num) return
                                    }
                                    toolLibrary.push({
                                        number: num,
                                        name: name,
                                        diameter: newToolDia.value / 10000.0,
                                        type: newToolType.currentText
                                    })
                                    newToolName.text = ""
                                    newToolNum.value = num + 1
                                    toolLibraryModel.refresh()
                                    refreshToolCombos()
                                }
                            }
                        }
                    }
                }

                GroupBox {
                    title: "Toolpath Assignment"
                    Layout.fillWidth: true
                    GridLayout {
                        columns: 2
                        anchors.fill: parent
                        columnSpacing: 8
                        rowSpacing: 6
                        Label { text: "Outline Cuts:" }
                        ComboBox {
                            id: outlineToolCombo
                            Layout.fillWidth: true
                            model: ListModel { id: outlineToolModel }
                            textRole: "text"
                            valueRole: "value"
                        }
                        Label { text: "Pocket Cuts:" }
                        ComboBox {
                            id: pocketToolCombo
                            Layout.fillWidth: true
                            model: ListModel { id: pocketToolModel }
                            textRole: "text"
                            valueRole: "value"
                        }
                    }
                }
            }

            // ==================== Tab 3: G-Code ====================
            ScrollView {
                RowLayout {
                    width: parent.width
                    spacing: 8

                    // Left column: Depths + Z Heights
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        GroupBox {
                            title: "Zero Reference"
                            Layout.fillWidth: true
                            GridLayout {
                                columns: 2
                                anchors.fill: parent
                                columnSpacing: 8
                                rowSpacing: 6

                                Label { text: "Z Zero From:" }
                                ComboBox {
                                    id: zeroFromCombo
                                    Layout.fillWidth: true
                                    model: ["Spoilboard", "Top of Sheet"]
                                }

                                Label { text: "" }
                                Label {
                                    text: zeroFromCombo.currentIndex === 0
                                        ? "Z=0 at spoilboard surface. Material top is positive Z."
                                        : "Z=0 at material top. Cuts go into negative Z."
                                    font.pixelSize: 11
                                    opacity: 0.6
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        GroupBox {
                            title: "Depths"
                            Layout.fillWidth: true
                            GridLayout {
                                columns: 2
                                anchors.fill: parent
                                columnSpacing: 8
                                rowSpacing: 6

                                Label { text: "Cut Depth Adjustment:" }
                                SpinBox {
                                    id: cutDepthAdjustment
                                    Layout.fillWidth: true
                                    from: -2500; to: 2500; stepSize: 10
                                    property real realValue: value / 10000.0
                                    onRealValueChanged: value = Math.round(realValue * 10000)
                                    textFromValue: function(v) {
                                        let inches = v / 10000.0
                                        let display = toDisplay(Math.abs(inches)).toFixed(4)
                                        let sign = inches >= 0 ? "+" : "-"
                                        return sign + display + lenSuffix()
                                    }
                                }

                                Label { text: "" }
                                Label {
                                    text: "Adjusts final cut depth relative to pallet thickness"
                                    font.pixelSize: 11; opacity: 0.6
                                    wrapMode: Text.WordWrap; Layout.fillWidth: true
                                }

                                Label { text: "Roughing Pass:" }
                                SpinBox {
                                    id: roughingPct
                                    Layout.fillWidth: true
                                    from: 50; to: 99; stepSize: 1; value: 80
                                    textFromValue: function(v) { return v + "% of thickness" }
                                }

                                Label { text: "Pocket Clearance:" }
                                SpinBox {
                                    id: pocketClearance
                                    Layout.fillWidth: true
                                    from: 0; to: 5000; stepSize: 1
                                    property real realValue: value / 10000.0
                                    onRealValueChanged: value = Math.round(realValue * 10000)
                                    textFromValue: function(v) { return toDisplay(v / 10000.0).toFixed(4) + lenSuffix() }
                                }
                            }
                        }

                        GroupBox {
                            title: "Z Heights"
                            Layout.fillWidth: true
                            GridLayout {
                                columns: 2
                                anchors.fill: parent
                                columnSpacing: 8
                                rowSpacing: 6

                                Label { text: "Safe Z:" }
                                SpinBox {
                                    id: safeZ
                                    Layout.fillWidth: true
                                    from: 10; to: 20000; stepSize: 10
                                    property real realValue: value / 10000.0
                                    onRealValueChanged: value = Math.round(realValue * 10000)
                                    textFromValue: function(v) { return toDisplay(v / 10000.0).toFixed(4) + lenSuffix() }
                                }

                                Label { text: "Retract Z:" }
                                SpinBox {
                                    id: retractZ
                                    Layout.fillWidth: true
                                    from: 10; to: 20000; stepSize: 10
                                    property real realValue: value / 10000.0
                                    onRealValueChanged: value = Math.round(realValue * 10000)
                                    textFromValue: function(v) { return toDisplay(v / 10000.0).toFixed(4) + lenSuffix() }
                                }
                            }
                        }
                    }

                    // Right column: Spindle + Feeds + End Position
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        GroupBox {
                            title: "Spindle"
                            Layout.fillWidth: true
                            GridLayout {
                                columns: 2
                                anchors.fill: parent
                                Label { text: "Speed:" }
                                SpinBox { id: spindleRpm; from: 1000; to: 30000; stepSize: 1000; value: 18000; Layout.fillWidth: true; textFromValue: function(v) { return v + " RPM" } }
                            }
                        }

                        GroupBox {
                            title: "Feed Rates"
                            Layout.fillWidth: true
                            GridLayout {
                                columns: 2
                                anchors.fill: parent
                                columnSpacing: 8
                                rowSpacing: 6
                                Label { text: "XY Roughing:" }
                                SpinBox { id: feedXyRough; from: 10; to: 50000; stepSize: 10; value: 650; Layout.fillWidth: true; textFromValue: function(v) { return Math.round(toDisplay(v)) + feedSuffix() } }
                                Label { text: "XY Finishing:" }
                                SpinBox { id: feedXyFinish; from: 10; to: 50000; stepSize: 10; value: 350; Layout.fillWidth: true; textFromValue: function(v) { return Math.round(toDisplay(v)) + feedSuffix() } }
                                Label { text: "Z Plunge:" }
                                SpinBox { id: feedZ; from: 5; to: 12500; stepSize: 5; value: 60; Layout.fillWidth: true; textFromValue: function(v) { return Math.round(toDisplay(v)) + feedSuffix() } }
                            }
                        }

                        GroupBox {
                            title: "Lead-In Ramp"
                            Layout.fillWidth: true
                            GridLayout {
                                columns: 2
                                anchors.fill: parent
                                columnSpacing: 8
                                rowSpacing: 6
                                Label { text: "Ramp Angle:" }
                                SpinBox {
                                    id: rampAngle
                                    Layout.fillWidth: true
                                    from: 5; to: 450; stepSize: 5; value: 50
                                    property real realValue: value / 10.0
                                    onRealValueChanged: value = Math.round(realValue * 10)
                                    textFromValue: function(v) { return (v / 10.0).toFixed(1) + "°" }
                                }
                                Label { text: "" }
                                Label {
                                    text: "Angle from horizontal. Higher = steeper ramp. Lead-in prefers vertical edges."
                                    font.pixelSize: 11; opacity: 0.6
                                    wrapMode: Text.WordWrap; Layout.fillWidth: true
                                }
                            }
                        }

                        GroupBox {
                            title: "End Position"
                            Layout.fillWidth: true
                            GridLayout {
                                columns: 2
                                anchors.fill: parent
                                columnSpacing: 8
                                rowSpacing: 6
                                Label { text: "Offset Past Sheet:" }
                                SpinBox {
                                    id: endPositionOffset
                                    Layout.fillWidth: true
                                    from: 0; to: 500000; stepSize: 100
                                    property real realValue: value / 10000.0
                                    onRealValueChanged: value = Math.round(realValue * 10000)
                                    textFromValue: function(v) { return toDisplay(v / 10000.0).toFixed(2) + lenSuffix() }
                                }
                                Label { text: "End Z Height:" }
                                SpinBox {
                                    id: endZHeight
                                    Layout.fillWidth: true
                                    from: 10; to: 100000; stepSize: 100
                                    property real realValue: value / 10000.0
                                    onRealValueChanged: value = Math.round(realValue * 10000)
                                    textFromValue: function(v) { return toDisplay(v / 10000.0).toFixed(2) + lenSuffix() }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Bottom buttons
        RowLayout {
            spacing: 8
            Button {
                text: "Restore Defaults"
                onClicked: {
                    isMetric = false
                    gcodeSettings = JSON.parse(settingsController.defaultGcodeSettingsJson())
                    toolLibrary = JSON.parse(settingsController.defaultToolLibraryJson())
                    loadGcodeToSpinboxes()
                    toolLibraryModel.refresh()
                    refreshToolCombos()
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                visible: !firstRun
                text: "Cancel"
                onClicked: setupDialog.reject()
            }
            Button {
                text: firstRun ? "Save & Continue" : "Save"
                highlighted: true
                onClicked: {
                    let name = deviceNameField.text.trim()
                    let hf = hotFolderField.text.trim()
                    if (!name || !hf) return

                    let gcode = collectGcodeFromSpinboxes()
                    settingsController.saveAllSettings(
                        name,
                        apiKeyField.text.trim(),
                        apiUrlField.text.trim(),
                        lanIpField.text.trim(),
                        machineLetterCombo.currentText,
                        hf,
                        JSON.stringify(gcode),
                        JSON.stringify(toolLibrary)
                    )
                    setupDialog.accept()
                }
            }
        }
    }

    // Helper: refresh tool library ListModel from JS array
    Component.onCompleted: {
        toolLibraryModel.refresh = function() {
            toolLibraryModel.clear()
            for (let t of toolLibrary) {
                toolLibraryModel.append({
                    toolNumber: t.number,
                    toolName: t.name,
                    toolDiameter: t.diameter,
                    toolType: t.type
                })
            }
        }
    }
}
