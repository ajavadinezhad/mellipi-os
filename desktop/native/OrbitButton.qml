import QtQuick 2.15
import "."
import QtQuick.Controls 2.15
Button {
    id: control
    property bool accent: false
    property bool quiet: false
    property bool bare: false
    property string hint: ""
    property bool enterHeld: false
    readonly property bool visuallyDown: down || enterHeld
    readonly property color primaryInk: background && background.foreground !== undefined ? background.foreground : Theme.accentText
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
        text: control.text; font: control.font; color: !control.enabled ? Theme.disabled : control.accent ? control.primaryInk : Theme.text
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight; textFormat: Text.PlainText
    }
    background: ControlSurface {
        controlEnabled: control.enabled;focused: control.activeFocus
        hovered: !control.bare && control.hovered;pressed: !control.bare && control.visuallyDown
        primary: control.accent && !control.bare;quiet: control.quiet || control.bare;animate: true
    }
    onPressedChanged: if(pressed){enterHeld=false;Orbit.hideTooltip();}
    onHoveredChanged: {
        if(hovered && hint !== "") {Orbit.queueItemTooltip(control,hint,control.width/2,control.height);}
        else Orbit.hideTooltip();
    }
}
