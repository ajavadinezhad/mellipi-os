import QtQuick 2.15
import "."
OrbitButton {
    id: button
    property string kind: "apps"
    quiet: true;focusPolicy: Qt.NoFocus
    background: Rectangle { radius: Theme.corner(10);color: button.down || button.hovered ? Theme.hover : "transparent" }
    contentItem: Canvas {
        id: glyph;implicitWidth: 18;implicitHeight: 18
        onPaint: {
            var c=getContext("2d");c.clearRect(0,0,width,height);c.strokeStyle=Theme.text;c.lineWidth=1.5;c.lineJoin="round";
            var x=Math.round((width-18)/2);var y=Math.round((height-18)/2);
            if(button.kind==="fold") {c.beginPath();c.moveTo(x+9,y+1);c.lineTo(x+17,y+9);c.lineTo(x+9,y+17);c.lineTo(x+1,y+9);c.closePath();c.moveTo(x+5,y+9);c.lineTo(x+9,y+5);c.lineTo(x+13,y+9);c.moveTo(x+9,y+5);c.lineTo(x+9,y+17);c.stroke();}
            else if(button.kind==="apps") {c.strokeRect(x+3,y+3,4,4);c.strokeRect(x+11,y+3,4,4);c.strokeRect(x+3,y+11,4,4);c.strokeRect(x+11,y+11,4,4);}
            else {c.beginPath();c.moveTo(x+2,y+6);c.lineTo(x+6,y+6);c.lineTo(x+7,y+9);c.lineTo(x+11,y+9);c.lineTo(x+12,y+6);c.lineTo(x+16,y+6);c.lineTo(x+16,y+15);c.lineTo(x+2,y+15);c.closePath();c.stroke();c.beginPath();c.moveTo(x+5,y+3);c.lineTo(x+13,y+3);c.stroke();}
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Connections { target: Orbit;function onSettingsChanged(){glyph.requestPaint();} }
    }
}
