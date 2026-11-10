import QtQuick 2.15
import "."
import QtQuick.Controls 2.15
Button {
    id: control
    property bool accent: false
    property bool quiet: false
    property string hint: ""
    property bool enterHeld: false
    readonly property bool visuallyDown: down || enterHeld
    function pressEnter(event) {
        event.accepted=true;
        if(!event.isAutoRepeat && enabled && !pressed && !enterHeld) {enterHeld=true;Orbit.hideTooltip();}
    }
    Keys.onReturnPressed: event => pressEnter(event)
    Keys.onEnterPressed: event => pressEnter(event)
    Keys.onReleased: event => {
        if(event.key!==Qt.Key_Return && event.key!==Qt.Key_Enter){event.accepted=false;return;}
        event.accepted=true;
        if(event.isAutoRepeat)return;
        var activate=enterHeld;enterHeld=false;
        if(activate && enabled && visible && activeFocus && !pressed)clicked();
    }
    onActiveFocusChanged: if(!activeFocus)enterHeld=false
    onEnabledChanged: if(!enabled)enterHeld=false
    onVisibleChanged: if(!visible)enterHeld=false
    Accessible.name: text
    Accessible.description: hint
    implicitHeight: Math.max(Theme.extraCompact ? 26 : Theme.compact ? 30 : 38,Theme.fontSize(12)+(Theme.extraCompact ? 12 : 16))
    implicitWidth: Math.max(36, contentItem.implicitWidth + (Theme.compact ? 20 : 28))
    hoverEnabled: true
    font.family: "Inter"
    font.pixelSize: Theme.fontSize(12)
    padding: Theme.extraCompact ? 5 : Theme.compact ? 8 : 12
    contentItem: Text {
        text: control.text; font: control.font; color: !control.enabled ? Theme.disabled : control.accent ? Theme.accentText : Theme.text
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight; textFormat: Text.PlainText
    }
    background: Rectangle {
        id:buttonFill
        property bool ready:false
        readonly property color targetColor:control.accent ? (control.visuallyDown ? Qt.darker(Theme.accent,1.15) : control.hovered ? Theme.accentHover : Theme.accent) : control.visuallyDown ? Theme.hover : control.hovered ? Theme.hover : control.quiet ? "transparent" : Theme.surface
        onTargetColorChanged:{pressFade.stop();pressFade.to=targetColor;if(ready && !Theme.reducedMotion)pressFade.restart();else color=targetColor;}
        Component.onCompleted:{color=targetColor;ready=true;}
        radius: Theme.corner(Theme.compact ? 10 : 12)
        border.color: control.activeFocus ? (control.accent ? Theme.accentText : Theme.focusColor) : control.accent || control.quiet ? "transparent" : Theme.border
        border.width: control.activeFocus ? 2 : 1
        Rectangle {
            visible: Theme.fold && !control.accent && (control.visuallyDown || control.activeFocus)
            anchors.left: parent.left;anchors.right: parent.right;anchors.bottom: parent.bottom
            anchors.leftMargin: 5;anchors.rightMargin: 5;height: 1;color: Theme.accent
        }
        ColorAnimation {id:pressFade;objectName:"buttonPressFade";target:buttonFill;property:"color";duration:control.visuallyDown ? Math.min(60,Theme.motion) : Theme.motion}
        readonly property bool motionDisabled:Theme.reducedMotion
        onMotionDisabledChanged:if(motionDisabled){pressFade.stop();buttonFill.color=buttonFill.targetColor;}
    }
    onPressedChanged: if(pressed){enterHeld=false;Orbit.hideTooltip();}
    onHoveredChanged: {
        if(hovered && hint !== "") {Orbit.queueItemTooltip(control,hint,control.width/2,control.height);}
        else Orbit.hideTooltip();
    }
}
