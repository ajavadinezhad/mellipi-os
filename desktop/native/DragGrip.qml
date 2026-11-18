import QtQuick 2.15
import "."

Item {
    property color ink: Theme.muted
    implicitWidth: 12
    implicitHeight: 16
    Grid {
        anchors.centerIn: parent
        columns: 2; spacing: 2
        Repeater {
            model: 6
            Rectangle {width: 2; height: 2; radius: 1; color: ink}
        }
    }
}
