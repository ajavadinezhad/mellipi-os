import QtQuick 2.15
import "."
import QtQuick.Controls 2.15
TextField {
    id: field
    property string accessibleLabel: placeholderText
    Accessible.name: accessibleLabel
    color: Theme.text; placeholderTextColor: Theme.faint; font.pixelSize: Theme.fontSize(Theme.compact ? 14 : 16)
    selectByMouse: true; leftPadding: 17; rightPadding: 17; implicitHeight: Theme.extraCompact ? 32 : Theme.compact ? 42 : 54
    background: Rectangle { color: Theme.background; radius: Theme.corner(13); border.color: field.activeFocus ? Theme.focusColor : Theme.border;border.width: field.activeFocus && Theme.highContrast ? 2 : 1 }
}
