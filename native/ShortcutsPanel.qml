import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: panel;objectName: "shortcutsPanel";clip: true;contentWidth: availableWidth;implicitHeight: Math.min(480,content.implicitHeight)
    ColumnLayout {
        id: content;width: panel.availableWidth;spacing: 8
        Text {Layout.fillWidth: true;text: "Use Super, Ctrl, Alt or Shift plus a key, for example Super+F12. Leave blank to disable. Super+F10/F11/F12 are the default mute/down/up alternatives.";color: Theme.muted;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap}
        Repeater {
            model: Shortcuts.bindings
            ColumnLayout {
                required property var modelData
                Layout.fillWidth: true;spacing: 3
                Text {text: modelData.label;color: Theme.text;font.pixelSize: Theme.fontSize(11);Layout.fillWidth: true}
                RowLayout {
                    Layout.fillWidth: true;spacing: 4
                    OrbitField {id: field;objectName: "shortcut_"+modelData.action;Accessible.name: modelData.label+" shortcut";Layout.fillWidth: true;implicitHeight: 30;text: modelData.chord;maximumLength: 64;font.pixelSize: Theme.fontSize(11);onAccepted: Shortcuts.setBinding(modelData.action,text)}
                    IconButton {objectName: "shortcutSet_"+modelData.action;iconName:"check";hint:"Apply "+modelData.label+" shortcut";implicitHeight:30;enabled: Shortcuts.state.available && !Shortcuts.state.busy;onClicked: Shortcuts.setBinding(modelData.action,field.text)}
                    OrbitButton {objectName: "shortcutReset_"+modelData.action;text: "Reset";Accessible.name: "Reset "+modelData.label+" shortcut";quiet: true;implicitHeight: 28;enabled: Shortcuts.state.available && !Shortcuts.state.busy;onClicked: Shortcuts.resetBinding(modelData.action)}
                }
            }
        }
        Text {Layout.fillWidth: true;text: Shortcuts.state.error || (!Shortcuts.state.available ? "Shortcuts require an Abstract Wayland session." : "Changes apply immediately and persist for the next login.");color: Theme.muted;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap;textFormat: Text.PlainText}
    }
}
