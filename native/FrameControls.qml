import QtQuick 2.15
import QtQuick.Controls 2.15
import "."
Item {
    id: controls
    property string windowId: ""
    property bool maximized: false
    implicitWidth: 84;implicitHeight: 22
    Row {
        anchors.fill: parent;spacing: 0
        Repeater {
            model: ["minimize","maximize","close"]
            Button {
                id: frameButton
                required property string modelData
                property string pressedWindowId: ""
                objectName: "frame-"+modelData
                width: controls.width/3;height: controls.height;padding: 0
                focusPolicy: Qt.NoFocus;activeFocusOnTab: false;hoverEnabled: true
                enabled: controls.windowId.length>0
                onPressed: pressedWindowId=controls.windowId
                onCanceled: pressedWindowId=""
                onClicked: {
                    var target=pressedWindowId;pressedWindowId="";
                    // A focus change between press and release must not close a different app.
                    if(target==="" || target!==controls.windowId)return;
                    if(modelData==="minimize")Orbit.minimizeWindow(target);
                    else if(modelData==="maximize")Orbit.maximizeWindow(target);
                    else Orbit.closeWindow(target);
                }
                Accessible.name: modelData==="minimize" ? "Minimize window" : modelData==="close" ? "Close window" : controls.maximized ? "Restore window size" : "Maximize window"
                background: Rectangle {
                    radius: Theme.corner(3)
                    color: frameButton.down ? (frameButton.modelData==="close" ? "#96303e" : Theme.raised) : frameButton.hovered ? (frameButton.modelData==="close" ? "#b83b48" : Theme.hover) : "transparent"
                }
                contentItem: Canvas {
                    id: glyph
                    property color ink: frameButton.modelData==="close" && (frameButton.hovered || frameButton.down) ? "#ffffff" : Theme.text
                    property bool restored: controls.maximized
                    opacity: frameButton.enabled ? 1 : .4
                    onInkChanged: requestPaint()
                    onRestoredChanged: requestPaint()
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    onPaint: {
                        var context=getContext("2d");context.clearRect(0,0,width,height);
                        var cx=Math.floor(width/2)+.5;var cy=Math.floor(height/2)+.5;
                        context.strokeStyle=ink;context.lineWidth=1;context.lineCap="square";context.lineJoin="miter";
                        if(frameButton.modelData==="minimize") {
                            context.beginPath();context.moveTo(cx-4,cy+3);context.lineTo(cx+4,cy+3);context.stroke();
                        } else if(frameButton.modelData==="maximize") {
                            if(restored) {
                                context.beginPath();context.moveTo(cx-2,cy-5);context.lineTo(cx+5,cy-5);context.lineTo(cx+5,cy+2);context.stroke();
                                context.strokeRect(cx-4,cy-3,7,7);
                            } else context.strokeRect(cx-4,cy-4,8,8);
                        } else {
                            context.beginPath();context.moveTo(cx-4,cy-4);context.lineTo(cx+4,cy+4);context.moveTo(cx+4,cy-4);context.lineTo(cx-4,cy+4);context.stroke();
                        }
                    }
                }
            }
        }
    }
}
