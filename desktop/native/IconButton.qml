import QtQuick 2.15
import "."

OrbitButton {
    id: button
    property string iconName: ""
    property bool phosphor: false
    property int glyphSize: 16
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
        implicitWidth: button.text ? glyph.width + 6 + label.implicitWidth : button.glyphSize
        implicitHeight: Math.max(button.glyphSize, label.implicitHeight)
        Image {
            id: glyph;objectName:"iconGlyph"
            width: Math.max(0, Math.min(button.glyphSize,parent.width,parent.height)); height: width
            opacity: button.bare && button.visuallyDown ? .68 : 1
            x: button.text ? Math.max(0,(parent.width-parent.implicitWidth)/2) : Math.round((parent.width-width)/2)
            anchors.verticalCenter: parent.verticalCenter
            fillMode: Image.PreserveAspectFit
            sourceSize: button.phosphor ? Qt.size(Math.max(32, width*2),Math.max(32, height*2)) : Qt.size(24,24)
            source: !button.iconName ? "" : button.phosphor ? Theme.phosphorIconSource(button.iconName, ink) : Theme.symbolicIconSource(button.iconName, ink)
            readonly property color ink: !button.enabled ? Theme.disabled : button.accent && !button.bare ? button.primaryInk : button.glyphColor
        }
        Rectangle {
            visible: button.bare && button.accent
            width: 3;height: 3;radius: 2;color: glyph.ink
            anchors.horizontalCenter: glyph.horizontalCenter
            anchors.bottom: parent.bottom;anchors.bottomMargin: -2
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
