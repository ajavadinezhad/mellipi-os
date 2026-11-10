import QtQuick 2.15
import "."
OrbitButton {
    quiet: true;implicitWidth: 30;implicitHeight: 28;hint: "Screenshot · Print Screen"
    Accessible.name: "Screenshot"
    onClicked: Orbit.showPanel("screenshot")
    contentItem: Canvas {
        id: glyph;implicitWidth: 16;implicitHeight: 16
        onPaint: {
            var c=getContext("2d");c.clearRect(0,0,width,height);c.strokeStyle=Theme.text;c.lineWidth=1.4;c.lineJoin="round";
            var x=Math.round((width-16)/2);var y=Math.round((height-16)/2);
            c.beginPath();c.moveTo(x+2,y+5);c.lineTo(x+5,y+5);c.lineTo(x+6,y+3);c.lineTo(x+10,y+3);c.lineTo(x+11,y+5);c.lineTo(x+14,y+5);c.lineTo(x+14,y+13);c.lineTo(x+2,y+13);c.closePath();c.stroke();
            c.beginPath();c.arc(x+8,y+9,2.5,0,Math.PI*2);c.stroke();
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Connections { target: Orbit;function onSettingsChanged(){glyph.requestPaint();} }
    }
}
