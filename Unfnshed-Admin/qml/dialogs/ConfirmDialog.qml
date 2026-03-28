import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: confirmDialog
    title: "Confirm"
    modal: true
    anchors.centerIn: Overlay.overlay
    width: 360
    standardButtons: Dialog.Yes | Dialog.No

    property string message: ""

    Label {
        text: confirmDialog.message
        wrapMode: Text.WordWrap
        width: parent.width
    }
}
