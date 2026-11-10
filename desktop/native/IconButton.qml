import QtQuick 2.15
import "."

OrbitButton {
    id: button
    property string iconName: ""
    property string accessibleLabel: hint
    implicitWidth: 30
    implicitHeight: 30
    padding: 6
    quiet: true
    text: ""
    Accessible.name: accessibleLabel
    Accessible.role: Accessible.Button
    function repaintGlyph() {if(glyph)glyph.requestPaint();}
    onIconNameChanged: repaintGlyph()
    onEnabledChanged: repaintGlyph()
    onAccentChanged: repaintGlyph()
    contentItem: Canvas {
        id: glyph
        implicitWidth: 16;implicitHeight: 16
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var c=getContext("2d");c.clearRect(0,0,width,height);c.save();
            c.translate(Math.round((width-16)/2),Math.round((height-16)/2));
            var ink=!button.enabled ? Theme.disabled : button.accent ? Theme.accentText : Theme.text;
            c.strokeStyle=ink;c.fillStyle=ink;c.lineWidth=1.5;c.lineCap="round";c.lineJoin="round";
            c.beginPath();
            if(button.iconName==="camera" || button.iconName==="screenshot") {
                c.moveTo(2,5);c.lineTo(5,5);c.lineTo(6,3);c.lineTo(10,3);c.lineTo(11,5);c.lineTo(14,5);c.lineTo(14,13);c.lineTo(2,13);c.closePath();c.stroke();c.beginPath();c.arc(8,9,2.5,0,Math.PI*2);
            } else if(button.iconName==="bell" || button.iconName==="notification") {
                c.moveTo(3,11);c.lineTo(4,9);c.lineTo(4,6);c.bezierCurveTo(4,1.5,12,1.5,12,6);c.lineTo(12,9);c.lineTo(13,11);c.closePath();c.moveTo(6.5,13);c.bezierCurveTo(7,14.5,9,14.5,9.5,13);
            } else if(button.iconName==="settings" || button.iconName==="controls") {
                for(var row=0;row<3;row++) {
                    var yy=4+row*4;var xx=row===1 ? 10 : 5;
                    c.moveTo(2,yy);c.lineTo(xx-2,yy);c.moveTo(xx+2,yy);c.lineTo(14,yy);c.strokeRect(xx-1.5,yy-1.5,3,3);
                }
            } else if(button.iconName==="wifi" || button.iconName==="network") {
                c.arc(8,12,9,-Math.PI*.75,-Math.PI*.25);c.moveTo(8+5.5*Math.cos(-Math.PI*.75),12+5.5*Math.sin(-Math.PI*.75));c.arc(8,12,5.5,-Math.PI*.75,-Math.PI*.25);c.moveTo(8+2*Math.cos(-Math.PI*.75),12+2*Math.sin(-Math.PI*.75));c.arc(8,12,2,-Math.PI*.75,-Math.PI*.25);c.moveTo(8,14);c.lineTo(8,14.1);
            } else if(button.iconName==="battery") {
                c.rect(1.5,4,11.5,8);c.moveTo(15,6.5);c.lineTo(15,9.5);c.moveTo(4,6.5);c.lineTo(4,9.5);c.moveTo(7,6.5);c.lineTo(7,9.5);
            } else if(button.iconName==="user") {
                c.arc(8,5,2.5,0,Math.PI*2);c.moveTo(2.5,14);c.bezierCurveTo(2.5,8.5,13.5,8.5,13.5,14);
            } else if(button.iconName==="usage") {
                c.rect(2,9,2,5);c.rect(7,3,2,11);c.rect(12,6,2,8);
            } else if(button.iconName==="chevron-up" || button.iconName==="chevron-down") {
                var up=button.iconName==="chevron-up";c.moveTo(3,up ? 10 : 6);c.lineTo(8,up ? 5 : 11);c.lineTo(13,up ? 10 : 6);
            } else if(button.iconName==="chevron-left" || button.iconName==="chevron-right") {
                var left=button.iconName==="chevron-left";c.moveTo(left ? 10 : 6,3);c.lineTo(left ? 5 : 11,8);c.lineTo(left ? 10 : 6,13);
            } else if(button.iconName==="fold") {
                c.moveTo(8,1);c.lineTo(15,8);c.lineTo(8,15);c.lineTo(1,8);c.closePath();c.moveTo(4,8);c.lineTo(8,4);c.lineTo(12,8);c.moveTo(8,4);c.lineTo(8,15);
            } else if(button.iconName==="microphone" || button.iconName==="microphone-mute") {
                c.moveTo(5.5,4);c.bezierCurveTo(5.5,.5,10.5,.5,10.5,4);c.lineTo(10.5,7);c.bezierCurveTo(10.5,10.5,5.5,10.5,5.5,7);c.closePath();
                c.moveTo(3.5,7);c.bezierCurveTo(3.5,13,12.5,13,12.5,7);c.moveTo(8,12);c.lineTo(8,14);c.moveTo(6,14);c.lineTo(10,14);
                if(button.iconName==="microphone-mute"){c.moveTo(2,2);c.lineTo(14,14);}
            } else if(button.iconName==="volume" || button.iconName==="mute") {
                c.moveTo(1.5,6);c.lineTo(4.5,6);c.lineTo(7.5,3.5);c.lineTo(7.5,12.5);c.lineTo(4.5,10);c.lineTo(1.5,10);c.closePath();c.stroke();c.beginPath();
                if(button.iconName==="mute") {c.moveTo(10.5,5.5);c.lineTo(14.5,10.5);c.moveTo(14.5,5.5);c.lineTo(10.5,10.5);}
                else {c.arc(7,8,4,-.72,.72);c.moveTo(7+6*Math.cos(-.72),8+6*Math.sin(-.72));c.arc(7,8,6,-.72,.72);}
            } else if(button.iconName==="play") {
                c.moveTo(5,3);c.lineTo(13,8);c.lineTo(5,13);c.closePath();
            } else if(button.iconName==="pause") {
                c.rect(4,3,2.5,10);c.rect(9.5,3,2.5,10);
            } else if(button.iconName==="previous") {
                c.moveTo(3,3);c.lineTo(3,13);c.moveTo(12.5,3);c.lineTo(5.5,8);c.lineTo(12.5,13);c.closePath();
            } else if(button.iconName==="next") {
                c.moveTo(13,3);c.lineTo(13,13);c.moveTo(3.5,3);c.lineTo(10.5,8);c.lineTo(3.5,13);c.closePath();
            } else if(button.iconName==="pin" || button.iconName==="pinned") {
                c.moveTo(5,2);c.lineTo(11,2);c.lineTo(10,5);c.lineTo(10,8);c.lineTo(13,10);c.lineTo(3,10);c.lineTo(6,8);c.lineTo(6,5);c.closePath();
                if(button.iconName==="pinned")c.fill();
                c.stroke();c.beginPath();c.moveTo(8,10);c.lineTo(8,15);
            } else if(button.iconName==="refresh") {
                c.arc(8,8,5,Math.PI*.15,Math.PI*1.9);c.moveTo(12.8,3);c.lineTo(12.8,6.5);c.lineTo(9.3,6.5);
            } else if(button.iconName==="check") {
                c.moveTo(3,8);c.lineTo(6.5,11.5);c.lineTo(13,4.5);
            } else if(button.iconName==="close") {
                c.moveTo(4,4);c.lineTo(12,12);c.moveTo(12,4);c.lineTo(4,12);
            }
            c.stroke();c.restore();
        }
        Connections { target: Orbit;function onSettingsChanged(){button.repaintGlyph();} }
    }
}
