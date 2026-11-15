import QtQuick 2.15
import "."
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
TextField {
    id: entry
    property string accessibleLabel: placeholderText
    FontMetrics { id: metrics; font: entry.font }
    Accessible.name: accessibleLabel
    color: Theme.text; placeholderTextColor: entry.enabled ? Theme.muted : Theme.disabled; font.pixelSize: Theme.fontSize(Theme.compact ? 14 : 16)
    selectionColor: Theme.accent; selectedTextColor: Theme.accentText
    selectByMouse: true
    leftPadding: Theme.extraCompact ? 8 : Theme.compact ? 11 : 15
    rightPadding: leftPadding
    topPadding: 4; bottomPadding: 4
    // Compact rows sometimes request 28 px, even when 150% text won't fit.
    Layout.minimumHeight: Math.ceil(metrics.height + topPadding + bottomPadding)
    implicitHeight: Math.max(Layout.minimumHeight, Theme.extraCompact ? 32 : Theme.compact ? 42 : 54)
    background: ControlSurface { field: true;controlEnabled: entry.enabled;focused: entry.activeFocus }
}
