import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
Switch {
    id: toggle
    property string label: ""
    readonly property bool settingsSwitch: true
    implicitWidth: 36;implicitHeight: 28;padding: 0
    Layout.minimumWidth: implicitWidth;Layout.maximumWidth: implicitWidth
    Layout.alignment: Qt.AlignVCenter
    Accessible.name: label
    indicator: Rectangle {
        x: Math.round((toggle.width-width)/2);y: Math.round((toggle.height-height)/2);width: 32;height: 18;radius: Theme.corner(9)
        color: !toggle.enabled ? Theme.background : toggle.checked ? Theme.accent : toggle.down ? Theme.hover : Theme.raised
        border.color: toggle.activeFocus ? (toggle.checked ? Theme.accentText : Theme.focusColor) : toggle.enabled ? Theme.controlBorder : Theme.border
        border.width: toggle.activeFocus ? 2 : toggle.checked && toggle.enabled ? 0 : 1
        MotionValue {id:thumbSlide;target:toggle.checked ? 17 : 3;duration:Theme.motion}
        Rectangle { x: thumbSlide.value;y: 3;width: 12;height: 12;radius: 6;color: !toggle.enabled ? Theme.disabled : toggle.checked ? Theme.accentText : Theme.muted }
    }
}
