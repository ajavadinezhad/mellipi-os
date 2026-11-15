import QtQuick 2.15
import "."

OrbitButton {
    id: button
    property string iconName: ""
    property bool phosphor: false
    property color glyphColor: Theme.accentInk
    property string accessibleLabel: hint
    implicitWidth: 30
    implicitHeight: 30
    padding: 6
    quiet: true
    text: ""
    Accessible.name: accessibleLabel
    Accessible.role: Accessible.Button
    contentItem: Item {
        implicitWidth: button.text ? glyph.width + 6 + label.implicitWidth : 16
        implicitHeight: Math.max(16, label.implicitHeight)
        Image {
            id: glyph
            width: Math.min(16,parent.width); height: width
            x: button.text ? Math.max(0,(parent.width-parent.implicitWidth)/2) : Math.round((parent.width-width)/2)
            anchors.verticalCenter: parent.verticalCenter
            fillMode: Image.PreserveAspectFit
            sourceSize: Qt.size(24,24)
            source: !button.iconName ? "" : button.phosphor ? "image://icons/phosphor/"+String(ink).slice(1)+"/"+button.iconName : Theme.symbolicIconSource(button.iconName, ink)
            readonly property color ink: !button.enabled ? Theme.disabled : button.accent ? Theme.accentText : button.glyphColor
        }
        Text {
            id: label
            visible: !!button.text
            text: button.text
            x: glyph.x + glyph.width + 6
            width: Math.max(0,parent.width-x)
            anchors.verticalCenter: parent.verticalCenter
            font: button.font
            color: glyph.ink
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }
    }
}
