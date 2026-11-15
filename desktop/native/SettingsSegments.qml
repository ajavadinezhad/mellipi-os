import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
Rectangle {
    id: segments
    property var options: []
    property var value
    property int segmentWidth: 52
    readonly property int selectedIndex: options.findIndex(option => option.value===value)
    readonly property real optionWidth: Math.max(0, (width - 4 - Math.max(0,options.length - 1)) / Math.max(1,options.length))
    readonly property int optionHeight: Math.max(24, Theme.fontSize(11) + 10)
    property bool indicatorReady: false
    function updateIndicator() {
        segmentSlide.stop();segmentSlide.to=selection.targetX;
        if(indicatorReady && selectedIndex>=0 && !Theme.reducedMotion)segmentSlide.restart();
        else selection.x=selection.targetX;
    }
    Component.onCompleted: {indicatorReady=true;selection.x=selection.targetX;}
    signal selected(var value)
    function focusOption(index) {
        const item=segmentRepeater.itemAt(index);
        if(item) item.forceActiveFocus(Qt.TabFocusReason);
    }
    function focusSelection() {
        focusOption(Math.max(0, selectedIndex));
    }
    implicitWidth: Math.ceil(segmentWidth * Math.max(1,Theme.textScale)) * options.length + Math.max(0,options.length-1) + 4
    implicitHeight: optionHeight + 4
    Layout.fillWidth: true;Layout.minimumWidth: 0
    radius: Theme.corner(9);color: Theme.background;border.color: Theme.controlBorder;border.width: Theme.surfaceOutline
    Rectangle {
        id: selection;objectName: "segmentSelection"
        visible: segments.selectedIndex>=0
        readonly property real targetX:2+Math.max(0,segments.selectedIndex)*(segments.optionWidth+1)
        onTargetXChanged:segments.updateIndicator()
        x:2;y:2
        width:segments.optionWidth;height:segments.optionHeight;radius:Theme.corner(8)
        color: Theme.selectedSurface
        Rectangle {anchors.horizontalCenter:parent.horizontalCenter;anchors.bottom:parent.bottom;anchors.bottomMargin:2;width:Math.min(parent.width,20);height:2;radius:1;color:Theme.accentInk}
    }
    NumberAnimation {id:segmentSlide;objectName:"segmentSlide";target:selection;property:"x";duration:Theme.motion;easing.type:Easing.OutCubic}
    readonly property bool motionDisabled:Theme.reducedMotion
    onMotionDisabledChanged:if(motionDisabled){segmentSlide.stop();selection.x=selection.targetX;}
    Row {
        id: segmentRow;x: 2;y: 2;spacing: 1
        Repeater {
            id: segmentRepeater
            model: segments.options
            Rectangle {
                required property var modelData
                required property int index
                activeFocusOnTab: segments.enabled && index===Math.max(0,segments.selectedIndex)
                Keys.onSpacePressed: segments.selected(modelData.value)
                Keys.onReturnPressed: segments.selected(modelData.value)
                Keys.onEnterPressed: segments.selected(modelData.value)
                Keys.onLeftPressed: segments.focusOption((index+segments.options.length-1)%segments.options.length)
                Keys.onRightPressed: segments.focusOption((index+1)%segments.options.length)
                Keys.onPressed: event => {
                    if(event.key===Qt.Key_Home){segments.focusOption(0);event.accepted=true;}
                    else if(event.key===Qt.Key_End){segments.focusOption(segments.options.length-1);event.accepted=true;}
                }
                width: segments.optionWidth;height: segments.optionHeight;radius: Theme.corner(8)
                border.width: activeFocus ? (Theme.highContrast ? 2 : 1) : 0;border.color: Theme.focusColor
                color: segments.value === modelData.value ? "transparent" : hit.pressed ? Theme.selectedSurface : hit.containsMouse ? Theme.hover : "transparent"
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
                Text { anchors.verticalCenter: parent.verticalCenter;x: modelData.glyph ? 21 : 3;width: Math.max(0,parent.width-x-3);text: modelData.label;color: !segments.enabled ? Theme.disabled : segments.value===modelData.value ? Theme.text : Theme.muted;font.pixelSize: Theme.fontSize(11);horizontalAlignment: Text.AlignHCenter;elide: Text.ElideRight }
                MouseArea { id: hit;anchors.fill: parent;hoverEnabled: true;enabled: segments.enabled;onClicked: {Orbit.hideTooltip();segments.selected(modelData.value);}onEntered: {Orbit.queueItemTooltip(hit,modelData.label,width/2,height);}onExited: Orbit.hideTooltip() }
                Accessible.name: modelData.label;Accessible.role: Accessible.RadioButton
                Accessible.checked: segments.value===modelData.value
                Accessible.onPressAction: if(segments.enabled) segments.selected(modelData.value)
            }
        }
    }
}
