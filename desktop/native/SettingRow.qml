import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
Item {
    id: row
    property string label: ""
    default property alias controls: controls.data
    readonly property int baseHeight: Theme.extraCompact ? 26 : Theme.compact ? 30 : 38
    readonly property int gap: Theme.extraCompact ? 5 : 8
    readonly property int leftInset: 6
    readonly property int rightInset: 3
    readonly property real readableLabelWidth: Math.min(labelMetrics.advanceWidth, Theme.fontSize(12) * 9)
    readonly property bool hasSwitch: {
        for (let i = 0; i < controls.children.length; ++i)
            if (controls.children[i].settingsSwitch === true) return true;
        return false;
    }
    readonly property bool stacked: width > 0 && controls.implicitWidth + readableLabelWidth + gap + leftInset + rightInset > width
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    implicitWidth: labelMetrics.advanceWidth + gap + controls.implicitWidth + leftInset + rightInset
    implicitHeight: Math.max(baseHeight, stacked
        ? rowLabel.implicitHeight + 3 + controls.implicitHeight
        : Math.max(rowLabel.implicitHeight, controls.implicitHeight))

    TextMetrics { id: labelMetrics; font: rowLabel.font; text: row.label }
    Text {
        id: rowLabel;objectName: "settingRowLabel"
        x: row.leftInset
        y: row.stacked ? 0 : Math.round((row.height - height) / 2)
        width: Math.max(0, row.stacked ? row.width - row.leftInset - row.rightInset
                                     : controls.x - row.gap - row.leftInset)
        text: row.label;color: row.enabled ? Theme.text : Theme.disabled;font.pixelSize: Theme.fontSize(12)
        textFormat: Text.PlainText;wrapMode: Text.Wrap
    }
    RowLayout {
        id: controls
        spacing: 4
        width: Math.min(implicitWidth, Math.max(0, row.width - row.leftInset - row.rightInset))
        height: implicitHeight
        x: row.stacked && !row.hasSwitch ? row.leftInset : row.width - row.rightInset - width
        y: row.stacked ? rowLabel.implicitHeight + 3 : Math.round((row.height - height) / 2)
    }
}
