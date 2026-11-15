import QtQuick 2.15
import "."

Item {
    id: mark
    property color ink: Theme.muted
    property bool check: false
    property bool up: false
    implicitWidth: 12
    implicitHeight: 12
    rotation: up && !check ? 180 : 0
    Rectangle {
        x: mark.check ? 1 : 1.3; y: mark.check ? 6.8 : 5
        width: mark.check ? 5.5 : 6.5
        height: 1.5; radius: .75; rotation: 42; color: mark.ink
    }
    Rectangle {
        x: mark.check ? 3.7 : 5; y: mark.check ? 5.2 : 5
        width: mark.check ? 8.5 : 6.5
        height: 1.5; radius: .75; rotation: -42; color: mark.ink
    }
}
