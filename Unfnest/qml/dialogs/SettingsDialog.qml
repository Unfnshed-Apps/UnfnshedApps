import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: settingsDialog
    title: "Settings"
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 500
    height: 420

    property bool isMetric: false
    readonly property real inchToMm: 25.4

    standardButtons: Dialog.Ok | Dialog.Cancel | Dialog.RestoreDefaults

    ColumnLayout {
        anchors.fill: parent
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

        // Sheet Size — values stored as int = realValue * 100 (2 decimal places)
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

                    textFromValue: function(value) {
                        return (value / 100).toFixed(2) + (isMetric ? " mm" : " in")
                    }
                    valueFromText: function(text) {
                        return Math.round(parseFloat(text) * 100)
                    }
                }

                Label { text: "Height:" }
                SpinBox {
                    id: heightSpin
                    from: isMetric ? 2500 : 100
                    to: isMetric ? 800000 : 30000
                    stepSize: isMetric ? 1000 : 100
                    editable: true
                    Layout.fillWidth: true

                    textFromValue: function(value) {
                        return (value / 100).toFixed(2) + (isMetric ? " mm" : " in")
                    }
                    valueFromText: function(text) {
                        return Math.round(parseFloat(text) * 100)
                    }
                }
            }
        }

        // Spacing — values stored as int = realValue * 1000 (3 decimal places)
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

                    textFromValue: function(value) {
                        return (value / 1000).toFixed(3) + (isMetric ? " mm" : " in")
                    }
                    valueFromText: function(text) {
                        return Math.round(parseFloat(text) * 1000)
                    }
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

                    textFromValue: function(value) {
                        return (value / 1000).toFixed(3) + (isMetric ? " mm" : " in")
                    }
                    valueFromText: function(text) {
                        return Math.round(parseFloat(text) * 1000)
                    }
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

    function setUnits(metric) {
        if (metric === isMetric) return
        let factor = metric ? inchToMm : (1.0 / inchToMm)

        // Read current display values, convert, then update isMetric, then set values
        let w = widthSpin.value / 100.0 * factor
        let h = heightSpin.value / 100.0 * factor
        let s = spacingSpin.value / 1000.0 * factor
        let m = marginSpin.value / 1000.0 * factor

        // Update isMetric (this reactively updates from/to/stepSize)
        isMetric = metric

        // Set converted values in new unit domain
        widthSpin.value = Math.round(w * 100)
        heightSpin.value = Math.round(h * 100)
        spacingSpin.value = Math.round(s * 1000)
        marginSpin.value = Math.round(m * 1000)
    }

    onOpened: {
        // Controller always stores values in inches
        isMetric = settingsController.isMetric()
        let sw = settingsController.sheetWidth()
        let sh = settingsController.sheetHeight()
        let ps = settingsController.partSpacing()
        let em = settingsController.edgeMargin()

        // Convert to display units if metric
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
    }

    onAccepted: {
        // Pass display-unit values to controller (it handles conversion to inches)
        let w = widthSpin.value / 100.0
        let h = heightSpin.value / 100.0
        let s = spacingSpin.value / 1000.0
        let m = marginSpin.value / 1000.0
        settingsController.saveSettings(w, h, s, m, isMetric)
    }

    onReset: {
        // Restore defaults (imperial, 48x96 in, 0.75 spacing/margin)
        isMetric = false
        widthSpin.value = 4800
        heightSpin.value = 9600
        spacingSpin.value = 750
        marginSpin.value = 750
    }
}
