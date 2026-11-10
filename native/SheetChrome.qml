import QtQuick 2.15
import "."
Canvas {
    id: paper
    property real cornerRadius: Theme.radius
    onCornerRadiusChanged: requestPaint()
    property color paperColor: Theme.background
    property color edgeColor: Theme.border
    onVisibleChanged: if(visible)requestPaint()
    onAvailableChanged: if(available)requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaperColorChanged: requestPaint()
    onEdgeColorChanged: requestPaint()
    onPaint: {
        var c=getContext("2d");c.clearRect(0,0,width,height);
        var radius=Math.min(cornerRadius,width/2,height/2);
        if(radius>0){
            c.beginPath();c.moveTo(radius,.5);c.lineTo(width-radius,.5);c.quadraticCurveTo(width-.5,.5,width-.5,radius);c.lineTo(width-.5,height-radius);c.quadraticCurveTo(width-.5,height-.5,width-radius,height-.5);c.lineTo(radius,height-.5);c.quadraticCurveTo(.5,height-.5,.5,height-radius);c.lineTo(.5,radius);c.quadraticCurveTo(.5,.5,radius,.5);c.closePath();c.fillStyle=paperColor;c.fill();c.strokeStyle=edgeColor;c.lineWidth=1;c.stroke();return;
        }
        c.beginPath();c.rect(.5,.5,width-1,height-1);
        c.fillStyle=paperColor;c.fill();c.strokeStyle=edgeColor;c.lineWidth=1;c.stroke();
    }
}
