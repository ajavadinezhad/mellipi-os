import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
RowLayout {
    id: row
    property string label: ""
    default property alias controls: controls.data
    Layout.fillWidth: true;Layout.minimumHeight: Theme.extraCompact ? 26 : Theme.compact ? 30 : 38;spacing: Theme.extraCompact ? 5 : 8
    Text { text: row.label;color: row.enabled ? Theme.text : Theme.disabled;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true;Layout.leftMargin: 6;elide: Text.ElideRight }
    RowLayout { id: controls;spacing: 4;Layout.rightMargin: 3 }
}
