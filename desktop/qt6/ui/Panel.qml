import QtQuick
import QtQuick.Controls
Window {
    width: 640
    height: 48
    color: mellipiLight ? "#faf9fd" : "#232634"
    Row {
        anchors.verticalCenter: parent.verticalCenter
        x: 12
        spacing: 8
        Button { text: "Mellipi"; onClicked: shell.toggleLauncher() }
        Repeater {
            model: 4
            Button {
                text: index + 1
                checked: shell.workspace === index + 1
                onClicked: shell.selectWorkspace(index + 1)
            }
        }
    }
    Row {
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        visible: mellipiLogin
        Button { text: "Lock"; onClicked: shell.lockSession() }

    }

}
