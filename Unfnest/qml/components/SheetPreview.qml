import QtQuick
import QtQuick.Controls
import Unfnest 1.0

Rectangle {
    id: previewRoot
    color: root.darkMode ? "#1a1a1a" : "#f5f5f5"

    property real zoomLevel: 1.0

    Flickable {
        id: flickable
        anchors.fill: parent
        clip: true
        contentWidth: previewItem.width * zoomLevel
        contentHeight: previewItem.height * zoomLevel
        boundsBehavior: Flickable.StopAtBounds

        SheetPreviewItem {
            id: previewItem
            width: flickable.width
            height: flickable.height
            darkMode: root.darkMode
            transformOrigin: Item.TopLeft
            scale: zoomLevel
        }

        WheelHandler {
            onWheel: function(event) {
                let factor = 1.15
                if (event.angleDelta.y > 0) {
                    previewRoot.zoomLevel = Math.min(previewRoot.zoomLevel * factor, 10.0)
                } else {
                    previewRoot.zoomLevel = Math.max(previewRoot.zoomLevel / factor, 0.1)
                }
            }
        }

        ScrollBar.vertical: ScrollBar {}
        ScrollBar.horizontal: ScrollBar {}
    }
}
