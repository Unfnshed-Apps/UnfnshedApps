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

    onOpened: {
        m1Field.text = "0.7087"
        m2Field.text = "0.7087"
        m3Field.text = "0.7087"
        m1Field.forceActiveFocus()
        m1Field.selectAll()
    }

    function computeAverage() {
        var v1 = parseFloat(m1Field.text) || 0
        var v2 = parseFloat(m2Field.text) || 0
        var v3 = parseFloat(m3Field.text) || 0
        return ((v1 + v2 + v3) / 3).toFixed(4)
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

        Label {
            text: "Thickness Measurements (inches)"
            font.bold: true
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
                text: "0.7087"
                validator: DoubleValidator { bottom: 0.1; top: 2.0; decimals: 4 }
                selectByMouse: true
                onTextChanged: avgLabel.text = "Average: " + root.computeAverage() + "\""
            }

            Label { text: "Measurement 2:" }
            TextField {
                id: m2Field
                Layout.fillWidth: true
                text: "0.7087"
                validator: DoubleValidator { bottom: 0.1; top: 2.0; decimals: 4 }
                selectByMouse: true
                onTextChanged: avgLabel.text = "Average: " + root.computeAverage() + "\""
            }

            Label { text: "Measurement 3:" }
            TextField {
                id: m3Field
                Layout.fillWidth: true
                text: "0.7087"
                validator: DoubleValidator { bottom: 0.1; top: 2.0; decimals: 4 }
                selectByMouse: true
                onTextChanged: avgLabel.text = "Average: " + root.computeAverage() + "\""
            }
        }

        Label {
            id: avgLabel
            text: "Average: 0.7087\""
            font.italic: true
            color: "#666"
        }

        // Buttons
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Item { Layout.fillWidth: true }

            Button {
                text: "Skip"
                enabled: !cuttingController.isBusy
                onClicked: {
                    root.close()
                    cuttingController.skipThickness()
                }
            }

            Button {
                text: "OK"
                highlighted: true
                enabled: !cuttingController.isBusy
                onClicked: {
                    var v1 = parseFloat(m1Field.text) || 0.7087
                    var v2 = parseFloat(m2Field.text) || 0.7087
                    var v3 = parseFloat(m3Field.text) || 0.7087
                    root.close()
                    cuttingController.setSheetThickness(v1, v2, v3)
                }
            }
        }
    }
}
