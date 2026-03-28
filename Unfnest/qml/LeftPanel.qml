import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "tabs"

Item {
    id: leftPanel
    clip: true

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabBar {
            id: tabBar
            Layout.fillWidth: true

            TabButton { text: "Products (SKU)" }
            TabButton { text: "Components" }
            TabButton { text: "Replenishment" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            ProductsTab {}
            ComponentsTab {}
            ReplenishmentTab {}
        }

        ControlBar {
            Layout.fillWidth: true
            currentTabIndex: tabBar.currentIndex
        }
    }

    // Expose current tab index for nesting controller
    property alias currentTabIndex: tabBar.currentIndex
}
