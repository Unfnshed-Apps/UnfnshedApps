import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: syncTab

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 16

        // ── Auto-Sync Settings ─────────────────────────────
        GroupBox {
            title: "Auto-Sync Settings"
            Layout.fillWidth: true

            GridLayout {
                anchors.fill: parent
                columns: 2
                columnSpacing: 12
                rowSpacing: 8

                Label { text: "Auto-Sync:" }
                CheckBox {
                    id: autoSyncCheck
                    text: "Enable automatic sync"
                    checked: syncController.autoSyncEnabled
                    onToggled: syncController.setAutoSync(checked)
                }

                Label { text: "Sync Interval:" }
                RowLayout {
                    spacing: 8
                    SpinBox {
                        id: intervalSpin
                        from: 1
                        to: 1440
                        value: syncController.syncInterval
                        editable: true
                        enabled: autoSyncCheck.checked
                        onValueModified: syncController.setInterval(value)
                    }
                    Label {
                        text: "minutes"
                        color: palette.placeholderText
                    }
                }
            }
        }

        // ── Sync Status ────────────────────────────────────
        GroupBox {
            title: "Sync Status"
            Layout.fillWidth: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                Label {
                    text: "Last sync: " + syncController.lastSync
                }

                Label {
                    text: autoSyncCheck.checked
                          ? "Next sync: Every " + intervalSpin.value + " minutes"
                          : "Next sync: Auto-sync disabled"
                    color: palette.placeholderText
                }

                Label {
                    text: syncController.syncStatus
                    visible: syncController.syncStatus !== ""
                    color: palette.placeholderText
                }

                ProgressBar {
                    Layout.fillWidth: true
                    indeterminate: true
                    visible: syncController.isSyncing
                }
            }
        }

        // ── Manual Sync ────────────────────────────────────
        GroupBox {
            title: "Manual Sync"
            Layout.fillWidth: true

            RowLayout {
                anchors.fill: parent

                Button {
                    text: "Sync Now"
                    highlighted: true
                    enabled: !syncController.isSyncing
                    onClicked: syncController.syncNow()
                }

                Item { Layout.fillWidth: true }
            }
        }

        Item { Layout.fillHeight: true }
    }

    // Update controls when settings are reloaded externally
    Connections {
        target: syncController
        function onAutoSyncEnabledChanged() { autoSyncCheck.checked = syncController.autoSyncEnabled }
        function onSyncIntervalChanged() { intervalSpin.value = syncController.syncInterval }
    }
}
