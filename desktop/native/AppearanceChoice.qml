import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: choice
    property string label: ""
    property string preference: ""
    property var options: []
    Layout.fillWidth: true;spacing: 6
    Text { text: choice.label;color: Theme.muted;font.pixelSize: Theme.fontSize(11) }
    Flow {
        Layout.fillWidth: true;Layout.preferredHeight: childrenRect.height;spacing: 6
        Repeater {
            model: choice.options
            OrbitButton {
                required property var modelData
                text: modelData.label;accent: Orbit.appearance[choice.preference] === modelData.value
                onClicked: Orbit.setPreference(choice.preference,modelData.value)
            }
        }
    }
}
