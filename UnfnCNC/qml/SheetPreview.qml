import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import UnfnCNC 1.0

GroupBox {
    id: root
    title: "Sheet Preview"

    property bool darkMode: false

    SheetPreviewItem {
        anchors.fill: parent
        darkMode: root.darkMode
    }
}
