import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: group
    property string title: ""
    default property alias rows: content.data
    Layout.fillWidth: true;spacing: Theme.extraCompact ? 3 : Theme.compact ? 5 : 8
    Text { text: Theme.fold ? group.title.toUpperCase() : group.title;color: Theme.muted;font.pixelSize: Theme.fontSize(11);font.letterSpacing: Theme.fold ? .8 : 0;visible: text.length>0;Layout.leftMargin: 3 }
    Rectangle {
        Layout.fillWidth: true;implicitHeight: content.height+(Theme.extraCompact ? 8 : Theme.compact ? 12 : 18)
        objectName: "settingsGroupBackground";radius: Theme.corner(12);color: Theme.surface;border.color: Theme.border;border.width: Theme.fold && radius===0 ? 0 : 1
        Rectangle {visible: Theme.fold && parent.radius===0;anchors.left: parent.left;anchors.right: parent.right;anchors.top: parent.top;height: 1;color: Theme.border}
        Rectangle {visible: Theme.fold && parent.radius===0;anchors.left: parent.left;anchors.right: parent.right;anchors.bottom: parent.bottom;height: 1;color: Theme.border}
        ColumnLayout { id: content;height: implicitHeight;anchors.left: parent.left;anchors.right: parent.right;anchors.top: parent.top;anchors.margins: Theme.extraCompact ? 4 : Theme.compact ? 6 : 9;spacing: Theme.extraCompact ? 1 : 2 }
    }
}
