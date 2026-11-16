import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
Item {
    id: header
    property string section: "MELLIPI"
    property string title: ""
    property string subtitle: ""
    property bool compact: false
    property bool dense: false
    signal closeRequested()
    implicitHeight: dense ? Math.max(32,Math.ceil(titleLabel.implicitHeight)+6) : compact ? Theme.fontSize(8)+Theme.fontSize(17)+20 : Theme.fontSize(8)+Theme.fontSize(23)+Theme.fontSize(10)+28
    RowLayout {
        anchors.fill: parent;anchors.bottomMargin: header.dense ? 3 : 8;spacing: 10
        Column {
            Layout.fillWidth: true;Layout.minimumWidth: 0;spacing: 3
            Text {visible: !header.dense;width: parent.width;text: header.section.toUpperCase();font.pixelSize: Theme.fontSize(8);font.letterSpacing: 1.5;color: Theme.accentInk;elide: Text.ElideRight}
            Row {
                width: parent.width;spacing: 10
                Text {id: titleLabel;text: header.title;font.pixelSize: Theme.fontSize(header.dense ? 14 : header.compact ? 17 : 23);font.weight: Font.Medium;color: Theme.text;elide: Text.ElideRight;width: Math.min(implicitWidth,parent.width)}
            }
            Text {visible: !header.dense && !header.compact && text.length>0;width: parent.width;text: header.subtitle;font.pixelSize: Theme.fontSize(10);color: Theme.muted;elide: Text.ElideRight;textFormat: Text.PlainText}
        }
        IconButton {objectName: "sheetCloseButton";iconName: "close";implicitWidth: 28;implicitHeight: 28;hint: "Close · Esc";onClicked: header.closeRequested()}
    }
    Rectangle {anchors.bottom: parent.bottom;width: 24;height: 2;color: Theme.accentInk}
}
