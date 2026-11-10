import QtQuick 2.15
import QtQuick.Controls 2.15
import "."
Switch {
    id: toggle
    property string label: ""
    implicitWidth: 36;implicitHeight: 28;padding: 0
    Accessible.name: label
    indicator: Rectangle {
        x: 2;y: 5;width: 32;height: 18;radius: 9
        color: !toggle.enabled ? Theme.border : toggle.checked ? Theme.accent : Theme.raised
        border.color: toggle.activeFocus ? Theme.focusColor : Theme.border
        border.width: toggle.activeFocus && Theme.highContrast ? 2 : 1
        Rectangle { x: toggle.checked ? 17 : 3;y: 3;width: 12;height: 12;radius: 6;color: toggle.checked ? Theme.accentText : Theme.muted
            Behavior on x { NumberAnimation { duration: Theme.motion;easing.type: Easing.OutCubic } }
        }
    }
}
