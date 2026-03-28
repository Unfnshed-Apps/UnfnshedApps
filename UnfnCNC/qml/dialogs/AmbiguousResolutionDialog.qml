import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    title: "Specify Damaged Components"
    anchors.centerIn: parent
    modal: true
    width: 400

    property int groupIndex: 0
    property string candidatesJson: "[]"
    property int damagedCount: 0
    property var candidates: []
    property int currentTotal: 0

    standardButtons: Dialog.Ok | Dialog.Cancel

    onAboutToShow: {
        candidates = JSON.parse(candidatesJson)
        currentTotal = 0
        spinRepeater.model = candidates
    }

    // Disable OK until total matches
    onCurrentTotalChanged: {
        let okBtn = root.standardButton(Dialog.Ok)
        if (okBtn) okBtn.enabled = (currentTotal === damagedCount)
    }

    onAccepted: {
        let resolutions = []
        for (let i = 0; i < candidates.length; i++) {
            let item = spinRepeater.itemAt(i)
            if (item) {
                let val = item.spinValue
                if (val > 0) {
                    resolutions.push({
                        "component_id": candidates[i].component_id,
                        "component_name": candidates[i].component_name,
                        "quantity": val
                    })
                }
            }
        }
        damageController.resolveAmbiguous(groupIndex, JSON.stringify(resolutions))
    }

    onRejected: {
        damageController.cancelDamage()
    }

    contentItem: ColumnLayout {
        spacing: 10

        Label {
            text: root.damagedCount + " damaged part(s) could be any of these components.\n" +
                  "Please specify how many of each are damaged:"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Repeater {
            id: spinRepeater

            delegate: RowLayout {
                Layout.fillWidth: true
                property int spinValue: spin.value

                Label {
                    text: modelData.component_name
                    Layout.fillWidth: true
                }
                SpinBox {
                    id: spin
                    from: 0
                    to: root.damagedCount
                    value: 0
                    onValueModified: {
                        // Recalculate total
                        let total = 0
                        for (let i = 0; i < spinRepeater.count; i++) {
                            let item = spinRepeater.itemAt(i)
                            if (item) total += item.spinValue
                        }
                        root.currentTotal = total
                    }
                }
            }
        }

        Label {
            text: "Total: " + root.currentTotal + " / " + root.damagedCount
            color: root.currentTotal === root.damagedCount ? palette.text : "#c80000"
        }
    }
}
