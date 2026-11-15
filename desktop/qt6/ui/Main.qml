import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 760
    height: 460
    minimumWidth: 360
    minimumHeight: 300
    title: "Mellipi · Qt 6 prototype"
    color: mellipiLight ? "#efedf4" : "#181a25"
    readonly property color surface: mellipiLight ? "#faf9fd" : "#232634"
    readonly property color ink: mellipiLight ? "#252437" : "#eeeef8"
    readonly property color accent: mellipiLight ? "#504397" : "#c1b3ff"

    Shortcut { sequence: "Ctrl+Space"; onActivated: launcher.open() }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        Item { Layout.fillHeight: true }
        Label {
            text: "Mellipi"
            color: root.ink
            font.pixelSize: 39
            Layout.alignment: Qt.AlignHCenter
        }
        Label {
            text: "Qt 6 Quick prototype"
            color: root.accent
            Layout.alignment: Qt.AlignHCenter
        }
        Item { Layout.fillHeight: true }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 50
            radius: 12
            color: root.surface
            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                Button {
                    text: "Open launcher"
                    onClicked: launcher.open()
                }
                Item { Layout.fillWidth: true }
                Label { text: "Ctrl+Space"; color: root.ink; rightPadding: 8 }
            }
        }
    }

    Popup {
        id: launcher
        anchors.centerIn: Overlay.overlay
        width: Math.min(430, root.width - 28)
        padding: 14
        focus: true
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 14; color: root.surface }
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: mellipiReducedMotion ? 0 : 110 }
        }
        onOpened: search.forceActiveFocus()
        contentItem: ColumnLayout {
            Label { text: "Launcher"; color: root.ink; font.pixelSize: 18 }
            TextField {
                id: search
                Layout.fillWidth: true
                placeholderText: "Search"
                color: root.ink
                placeholderTextColor: root.accent
                background: Rectangle { color: root.color; radius: 8 }
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "This surface tests opening, focus, and theme rendering."
                color: root.ink
            }
        }
    }
}
