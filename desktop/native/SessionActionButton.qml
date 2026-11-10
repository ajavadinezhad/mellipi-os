import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
OrbitButton {
    id: action
    property string iconName: ""
    implicitWidth: 76
    implicitHeight: Math.max(48, contentItem.implicitHeight+padding*2)
    padding: 5
    font.pixelSize: Theme.fontSize(10)
    onEnabledChanged: if(glyph)glyph.requestPaint()
    onIconNameChanged: if(glyph)glyph.requestPaint()
    Accessible.name: text
    Accessible.description: hint
    contentItem: ColumnLayout {
        spacing: 4
        Canvas {
            id: glyph;objectName: "sessionActionGlyph"
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 16;Layout.preferredHeight: 16
            onPaint: {
                var c=getContext("2d");c.clearRect(0,0,width,height);
                c.strokeStyle=action.enabled ? Theme.text : Theme.disabled;c.fillStyle=c.strokeStyle;
                c.lineWidth=1.4;c.lineCap="round";c.lineJoin="round";c.beginPath();
                if(action.iconName==="lock") {
                    c.rect(3,7,10,7);c.moveTo(5,7);c.lineTo(5,4);c.bezierCurveTo(5,0,11,0,11,4);c.lineTo(11,7);
                    c.moveTo(8,10);c.lineTo(8,11.5);
                } else if(action.iconName==="logout") {
                    c.moveTo(6,2);c.lineTo(2,2);c.lineTo(2,14);c.lineTo(6,14);
                    c.moveTo(6,8);c.lineTo(14,8);c.moveTo(10.5,4.5);c.lineTo(14,8);c.lineTo(10.5,11.5);
                } else if(action.iconName==="switch-user") {
                    c.arc(5,4,2,0,Math.PI*2);c.moveTo(1,11);c.bezierCurveTo(1,6.5,9,6.5,9,11);
                    c.moveTo(10,5);c.lineTo(14,5);c.lineTo(12,3);c.moveTo(14,11);c.lineTo(10,11);c.lineTo(12,13);
                } else if(action.iconName==="sleep") {
                    c.moveTo(11.5,1.5);c.bezierCurveTo(5,-.5,0,4,2,10);c.bezierCurveTo(4,16,12,16,14.5,10.5);
                    c.bezierCurveTo(8,12,5,6,11.5,1.5);
                } else if(action.iconName==="restart") {
                    c.arc(8,8,5.5,-Math.PI*.34,Math.PI*1.32);
                    c.moveTo(12.5,1.5);c.lineTo(12.5,5.5);c.lineTo(8.5,5.5);
                } else if(action.iconName==="shutdown") {
                    c.arc(8,8.5,5.5,-Math.PI*.3,Math.PI*1.3);c.moveTo(8,1);c.lineTo(8,7);
                }
                c.stroke();
            }
            Connections {target: Orbit;function onSettingsChanged(){glyph.requestPaint();}}
        }
        Text {
            Layout.fillWidth: true
            text: action.text;color: action.enabled ? Theme.text : Theme.disabled
            font: action.font;horizontalAlignment: Text.AlignHCenter;elide: Text.ElideRight
        }
    }
}
