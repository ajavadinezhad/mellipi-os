import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: group
    property string title: ""
    default property alias rows: content.data
    readonly property int rowMargin: Theme.extraCompact ? 3 : Theme.compact ? 5 : 7
    Layout.fillWidth: true;spacing: Theme.extraCompact ? 4 : Theme.compact ? 5 : 7
    Text { text: group.title;color: Theme.text;font.pixelSize: Theme.fontSize(12);font.weight: Font.DemiBold;visible: text.length>0;Layout.leftMargin: 6;Layout.topMargin: 2 }
    Rectangle {
        Layout.fillWidth: true;implicitHeight: content.height+2*group.rowMargin
        objectName: "settingsGroupBackground";radius: Theme.corner(12);color: "transparent";border.color: Theme.border;border.width: Theme.surfaceOutline
        ColumnLayout { id: content;height: implicitHeight;anchors.left: parent.left;anchors.right: parent.right;anchors.top: parent.top;anchors.margins: group.rowMargin;spacing: Theme.extraCompact ? 1 : 2 }
    }
}
