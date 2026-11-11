import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
Rectangle {
    id: segments
    property var options: []
    property var value
    property int segmentWidth: 52
    readonly property int selectedIndex: options.findIndex(option => option.value===value)
    property bool indicatorReady: false
    function updateIndicator() {
        segmentSlide.stop();segmentSlide.to=selection.targetX;
        if(indicatorReady && selectedIndex>=0 && !Theme.reducedMotion)segmentSlide.restart();
        else selection.x=selection.targetX;
    }
    Component.onCompleted: {indicatorReady=true;selection.x=selection.targetX;}
    signal selected(var value)
    function focusSelection() {
        for(var i=0;i<segmentRow.children.length;i++) {
            var item=segmentRow.children[i];
            if(item.modelData && item.modelData.value===value){item.forceActiveFocus(Qt.TabFocusReason);return;}
        }
    }
    implicitWidth: segmentRow.implicitWidth+4;implicitHeight: 28
    radius: Theme.corner(10);color: Theme.surface;border.color: Theme.border;border.width: Theme.surfaceOutline
    Rectangle {
        id: selection;objectName: "segmentSelection"
        visible: segments.selectedIndex>=0
        readonly property real targetX:2+Math.max(0,segments.selectedIndex)*(segments.segmentWidth+1)
        onTargetXChanged:segments.updateIndicator()
        x:2;y:2
        width:segments.segmentWidth;height:24;radius:Theme.corner(8)
        color:Theme.selectedSurface
        Rectangle {visible:Theme.fold;anchors.left:parent.left;anchors.right:parent.right;anchors.bottom:parent.bottom;anchors.leftMargin:4;anchors.rightMargin:4;height:2;color:Theme.accent}
    }
    NumberAnimation {id:segmentSlide;objectName:"segmentSlide";target:selection;property:"x";duration:Theme.motion;easing.type:Easing.OutCubic}
    readonly property bool motionDisabled:Theme.reducedMotion
    onMotionDisabledChanged:if(motionDisabled){segmentSlide.stop();selection.x=selection.targetX;}
    Row {
        id: segmentRow;x: 2;y: 2;spacing: 1
        Repeater {
            model: segments.options
            Rectangle {
                required property var modelData
                activeFocusOnTab: true
                Keys.onSpacePressed: segments.selected(modelData.value)
                Keys.onReturnPressed: segments.selected(modelData.value)
                width: segments.segmentWidth;height: 24;radius: Theme.corner(8)
                border.width: activeFocus ? 1 : 0;border.color: Theme.accent
                color: segments.value === modelData.value ? "transparent" : hit.containsMouse ? Theme.hover : "transparent"
                Canvas {
                    id: segmentGlyph;x: 6;anchors.verticalCenter: parent.verticalCenter;width: 12;height: 12;visible: !!modelData.glyph
                    property string kind: modelData.glyph || ""
                    property color ink: !segments.enabled ? Theme.disabled : segments.value===modelData.value ? Theme.text : Theme.muted
                    onKindChanged: requestPaint();onInkChanged: requestPaint()
                    onPaint: {
                        var c=getContext("2d");c.clearRect(0,0,width,height);c.strokeStyle=ink;c.lineWidth=1;c.lineCap="round";
                        c.beginPath();
                        if(kind==="controls") {for(var i=0;i<3;i++){var y=2.5+i*3.5;c.moveTo(1,y);c.lineTo(11,y);var x=i===1 ? 8 : 4;c.moveTo(x,y-1.5);c.lineTo(x,y+1.5);}}
                        else if(kind==="connections") {c.moveTo(6,3);c.lineTo(6,7);c.moveTo(2,9);c.lineTo(2,7);c.lineTo(10,7);c.lineTo(10,9);c.strokeRect(4.5,.5,3,3);c.strokeRect(.5,9,3,2.5);c.strokeRect(8,9,3,2.5);}
                        else if(kind==="power") {c.arc(6,6.5,4.5,-Math.PI*.3,Math.PI*1.3);c.moveTo(6,.5);c.lineTo(6,5);}
                        c.stroke();
                    }
                }
                Text { anchors.verticalCenter: parent.verticalCenter;x: modelData.glyph ? 21 : 3;width: parent.width-x-3;text: modelData.label;color: !segments.enabled ? Theme.disabled : segments.value===modelData.value ? Theme.text : Theme.muted;font.pixelSize: Theme.fontSize(11);horizontalAlignment: Text.AlignHCenter;elide: Text.ElideRight }
                MouseArea { id: hit;anchors.fill: parent;hoverEnabled: true;enabled: segments.enabled;onClicked: {Orbit.hideTooltip();segments.selected(modelData.value);}onEntered: {Orbit.queueItemTooltip(hit,modelData.label,width/2,height);}onExited: Orbit.hideTooltip() }
                Accessible.name: modelData.label;Accessible.role: Accessible.Button;Accessible.onPressAction: segments.selected(modelData.value)
            }
        }
    }
}
