import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    title: "Sheet Thickness"
    width: 420
    anchors.centerIn: parent
    modal: true
    standardButtons: Dialog.NoButton
    closePolicy: Dialog.NoAutoClose

    property bool useMetric: true
    property string lastM1: ""
    property string lastM2: ""
    property string lastM3: ""

    readonly property real mmDefault: 18.0
    readonly property real inDefault: 0.7087
    readonly property real mmToIn: 0.0393701

    onOpened: {
        useMetric = true
        var def = mmDefault.toFixed(2)
        m1Field.text = lastM1 || def
        m2Field.text = lastM2 || def
        m3Field.text = lastM3 || def
        updateAverage()
        m1Field.forceActiveFocus()
        m1Field.selectAll()
    }

    function computeAverage() {
        var v1 = parseFloat(m1Field.text) || 0
        var v2 = parseFloat(m2Field.text) || 0
        var v3 = parseFloat(m3Field.text) || 0
        return (v1 + v2 + v3) / 3
    }

    function updateAverage() {
        var avg = computeAverage()
        var suffix = useMetric ? " mm" : "\""
        avgLabel.text = "Average: " + avg.toFixed(useMetric ? 2 : 4) + suffix
    }

    function convertFields(toMetric) {
        var fields = [m1Field, m2Field, m3Field]
        for (var i = 0; i < fields.length; i++) {
            var val = parseFloat(fields[i].text) || 0
            if (toMetric) {
                fields[i].text = (val / mmToIn).toFixed(2)
            } else {
                fields[i].text = (val * mmToIn).toFixed(4)
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: 12

        Label {
            text: "Measure the sheet thickness at 3 points."
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            color: "#666"
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: "#ccc"
        }

        RowLayout {
            spacing: 8

            Label {
                text: "Thickness Measurements (" + (root.useMetric ? "mm" : "inches") + ")"
                font.bold: true
            }

            Item { Layout.fillWidth: true }

            Button {
                text: root.useMetric ? "Switch to inches" : "Switch to mm"
                font.pixelSize: 11
                onClicked: {
                    root.convertFields(!root.useMetric)
                    root.useMetric = !root.useMetric
                    root.updateAverage()
                }
            }
        }

        GridLayout {
            columns: 2
            Layout.fillWidth: true
            columnSpacing: 8
            rowSpacing: 6

            Label { text: "Measurement 1:" }
            TextField {
                id: m1Field
                Layout.fillWidth: true
                validator: DoubleValidator { bottom: 0; top: 100; decimals: 4 }
                selectByMouse: true
                onTextChanged: root.updateAverage()
            }

            Label { text: "Measurement 2:" }
            TextField {
                id: m2Field
                Layout.fillWidth: true
                validator: DoubleValidator { bottom: 0; top: 100; decimals: 4 }
                selectByMouse: true
                onTextChanged: root.updateAverage()
            }

            Label { text: "Measurement 3:" }
            TextField {
                id: m3Field
                Layout.fillWidth: true
                validator: DoubleValidator { bottom: 0; top: 100; decimals: 4 }
                selectByMouse: true
                onTextChanged: root.updateAverage()
            }
        }

        Label {
            id: avgLabel
            text: "Average: 18.00 mm"
            font.italic: true
            color: "#666"
        }

        // Buttons
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Item { Layout.fillWidth: true }

            Button {
                text: "Cancel"
                enabled: !cuttingController.isBusy
                onClicked: {
                    root.close()
                    cuttingController.cancelThickness()
                }
            }

            Button {
                text: "OK"
                highlighted: true
                enabled: !cuttingController.isBusy
                onClicked: {
                    // Save entered values for next time
                    root.lastM1 = m1Field.text
                    root.lastM2 = m2Field.text
                    root.lastM3 = m3Field.text

                    var v1 = parseFloat(m1Field.text) || root.mmDefault
                    var v2 = parseFloat(m2Field.text) || root.mmDefault
                    var v3 = parseFloat(m3Field.text) || root.mmDefault
                    // Convert to inches if metric
                    if (root.useMetric) {
                        v1 *= root.mmToIn
                        v2 *= root.mmToIn
                        v3 *= root.mmToIn
                    }
                    root.close()
                    cuttingController.setSheetThickness(v1, v2, v3)
                }
            }
        }
    }
}
