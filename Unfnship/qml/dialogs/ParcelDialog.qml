import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: parcelDialog
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 400
    title: "Parcel Dimensions"
    standardButtons: Dialog.Ok | Dialog.Cancel

    signal requestRates(real weight, real length, real width, real height)

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Label {
            text: "Enter the parcel weight and dimensions to fetch shipping rates."
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            font.pixelSize: 12
            color: palette.placeholderText
        }

        GridLayout {
            columns: 2
            Layout.fillWidth: true
            columnSpacing: 8
            rowSpacing: 8

            Label { text: "Weight (lbs):" }
            TextField {
                id: weightField
                Layout.fillWidth: true
                text: "5.0"
                validator: DoubleValidator { bottom: 0.01; decimals: 2 }
                inputMethodHints: Qt.ImhFormattedNumbersOnly
            }

            Label { text: "Length (in):" }
            TextField {
                id: lengthField
                Layout.fillWidth: true
                text: "12"
                validator: DoubleValidator { bottom: 0.01; decimals: 2 }
                inputMethodHints: Qt.ImhFormattedNumbersOnly
            }

            Label { text: "Width (in):" }
            TextField {
                id: widthField
                Layout.fillWidth: true
                text: "8"
                validator: DoubleValidator { bottom: 0.01; decimals: 2 }
                inputMethodHints: Qt.ImhFormattedNumbersOnly
            }

            Label { text: "Height (in):" }
            TextField {
                id: heightField
                Layout.fillWidth: true
                text: "4"
                validator: DoubleValidator { bottom: 0.01; decimals: 2 }
                inputMethodHints: Qt.ImhFormattedNumbersOnly
            }
        }
    }

    onAccepted: {
        let w = parseFloat(weightField.text) || 0
        let l = parseFloat(lengthField.text) || 0
        let wd = parseFloat(widthField.text) || 0
        let h = parseFloat(heightField.text) || 0
        if (w > 0 && l > 0 && wd > 0 && h > 0) {
            parcelDialog.requestRates(w, l, wd, h)
        }
    }
}
