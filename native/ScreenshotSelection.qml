import QtQuick 2.15
import "."
Item {
    id: selection
    focus: true
    property bool dragging: false
    property real startX: 0
    property real startY: 0
    property real endX: 0
    property real endY: 0
    readonly property real selectionLeft: Math.min(startX,endX)
    readonly property real selectionTop: Math.min(startY,endY)
    readonly property real selectionWidth: Math.abs(endX-startX)
    readonly property real selectionHeight: Math.abs(endY-startY)
    function clampX(x) { return Math.max(0,Math.min(width,x)); }
    function clampY(y) { return Math.max(0,Math.min(height,y)); }
    function reset() { dragging=false;startX=0;startY=0;endX=0;endY=0; }
    function cancel() { reset();Screenshots.cancelArea(); }
    function capture() {
        var left=Math.round(selectionLeft),top=Math.round(selectionTop);
        var right=Math.round(selectionLeft+selectionWidth),bottom=Math.round(selectionTop+selectionHeight);
        if(right-left<4 || bottom-top<4) { cancel();return; }
        var global=Orbit.itemScreenPoint(selection,left,top);
        dragging=false;
        Screenshots.captureArea(Math.round(global.x),Math.round(global.y),right-left,bottom-top);
    }
    onWidthChanged: {startX=clampX(startX);endX=clampX(endX);}
    onHeightChanged: {startY=clampY(startY);endY=clampY(endY);}
    Component.onCompleted: forceActiveFocus()
    onVisibleChanged: if(visible) {reset();forceActiveFocus();}
    Keys.onEscapePressed: cancel()
    Keys.onReturnPressed: if(dragging) capture()
    Connections {
        target: Screenshots;ignoreUnknownSignals: true
        function onChanged() {
            if(Screenshots.state.selecting) selection.forceActiveFocus();
            else selection.reset();
        }
    }
    Rectangle { x: 0;y: 0;width: parent.width;height: selection.selectionTop;color: "#66000000" }
    Rectangle { x: 0;y: selection.selectionTop+selection.selectionHeight;width: parent.width;height: parent.height-y;color: "#66000000" }
    Rectangle { x: 0;y: selection.selectionTop;width: selection.selectionLeft;height: selection.selectionHeight;color: "#66000000" }
    Rectangle { x: selection.selectionLeft+selection.selectionWidth;y: selection.selectionTop;width: parent.width-x;height: selection.selectionHeight;color: "#66000000" }
    Rectangle {
        x: selection.selectionLeft;y: selection.selectionTop;width: selection.selectionWidth;height: selection.selectionHeight
        visible: selection.dragging && width>0 && height>0;color: "transparent";border.width: 2;border.color: Theme.accent
    }
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter;y: 20
        width: instructions.implicitWidth+24;height: 32;radius: Theme.corner(7);color: Theme.surface;border.color: Theme.border
        Text { id: instructions;anchors.centerIn: parent;text: "Drag to select · Esc to cancel";color: Theme.text;font.pixelSize: Theme.fontSize(12);textFormat: Text.PlainText }
    }
    Rectangle {
        visible: selection.dragging && selection.selectionWidth>=4 && selection.selectionHeight>=4
        width: dimensions.implicitWidth+16;height: 24;radius: Theme.corner(5);color: Theme.surface;border.color: Theme.border
        x: Math.max(8,Math.min(parent.width-width-8,selection.selectionLeft+selection.selectionWidth+8))
        y: Math.max(8,Math.min(parent.height-height-8,selection.selectionTop+selection.selectionHeight+8))
        Text { id: dimensions;anchors.centerIn: parent;text: Math.round(selection.selectionWidth)+" × "+Math.round(selection.selectionHeight);color: Theme.text;font.pixelSize: Theme.fontSize(11);textFormat: Text.PlainText }
    }
    MouseArea {
        anchors.fill: parent;acceptedButtons: Qt.LeftButton | Qt.RightButton;cursorShape: Qt.CrossCursor
        onPressed: mouse => {
            selection.forceActiveFocus();
            if(mouse.button===Qt.RightButton) {selection.cancel();return;}
            selection.startX=selection.clampX(mouse.x);selection.startY=selection.clampY(mouse.y);
            selection.endX=selection.startX;selection.endY=selection.startY;selection.dragging=true;
        }
        onPositionChanged: mouse => {if(selection.dragging){selection.endX=selection.clampX(mouse.x);selection.endY=selection.clampY(mouse.y);}}
        onReleased: mouse => {
            if(mouse.button!==Qt.LeftButton || !selection.dragging)return;
            selection.endX=selection.clampX(mouse.x);selection.endY=selection.clampY(mouse.y);selection.capture();
        }
        onCanceled: selection.reset()
    }
}
