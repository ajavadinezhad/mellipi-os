import QtQuick 2.15
import "."

FocusScope {
    id: navigation
    objectName: "workspaceNavigation"
    property string current: "launcher"
    property bool aiEnabled: false
    property var counts: ({})
    signal selected(string view)
    implicitWidth: 600
    implicitHeight: 44
    readonly property color activeInk: Theme.light ? Qt.darker(Theme.accent,1.8) : Theme.accent
    readonly property var sections: aiEnabled ? [
        {id:"launcher",label:"Apps",spoken:"Applications",glyph:"apps"},
        {id:"overview",label:"Windows",spoken:"Windows",glyph:"windows"},
        {id:"ai",label:"Intelligence",spoken:"Intelligence",glyph:"ai"}
    ] : [
        {id:"launcher",label:"Apps",spoken:"Applications",glyph:"apps"},
        {id:"overview",label:"Windows",spoken:"Windows",glyph:"windows"}
    ]
    function countFor(view) {
        var value=counts && counts[view];
        return typeof value==="number" && isFinite(value) && value>0 ? Math.floor(value) : 0;
    }
    function activateView(view) {if(view!==current)selected(view);}
    function moveFocus(index) {
        var count=sections.length;
        var next=(index+count)%count;
        var item=sectionTabs.itemAt(next);
        if(item) {item.forceActiveFocus(Qt.TabFocusReason);activateView(sections[next].id);}
    }
    Rectangle { anchors.left: parent.left;anchors.right: parent.right;anchors.bottom: parent.bottom;height: 1;color: Theme.border;opacity: .65 }
    Row {
        anchors.fill: parent;spacing: 4
        Repeater {
            id: sectionTabs
            model: navigation.sections
            FocusScope {
                id: tab
                required property var modelData
                required property int index
                objectName: "workspaceTab_"+modelData.id
                width: (navigation.width-4*(navigation.sections.length-1))/navigation.sections.length
                height: navigation.height
                activeFocusOnTab: true
                readonly property bool active: navigation.current===modelData.id
                readonly property int count: navigation.countFor(modelData.id)
                Keys.onLeftPressed: event => {navigation.moveFocus(index-1);event.accepted=true;}
                Keys.onRightPressed: event => {navigation.moveFocus(index+1);event.accepted=true;}
                Keys.onPressed: event => {
                    if(event.key===Qt.Key_Home) {navigation.moveFocus(0);event.accepted=true;}
                    else if(event.key===Qt.Key_End) {navigation.moveFocus(navigation.sections.length-1);event.accepted=true;}
                    else event.accepted=false;
                }
                Keys.onSpacePressed: event => {navigation.activateView(modelData.id);event.accepted=true;}
                Keys.onReturnPressed: event => {navigation.activateView(modelData.id);event.accepted=true;}
                Keys.onEnterPressed: event => {navigation.activateView(modelData.id);event.accepted=true;}
                Rectangle {
                    anchors.fill: parent;anchors.topMargin: 3;anchors.bottomMargin: 5
                    radius: Theme.corner(7)
                    color: hit.containsMouse ? Theme.hover : tab.active ? Qt.rgba(Theme.accent.r,Theme.accent.g,Theme.accent.b,.055) : "transparent"
                    border.width: tab.activeFocus ? 1 : 0;border.color: navigation.activeInk
                    Behavior on color { ColorAnimation { duration: Theme.motion } }
                }
                Row {
                    anchors.centerIn: parent;anchors.verticalCenterOffset: -1;spacing: 8
                    Canvas {
                        id: glyph;width: 16;height: 16;visible: tab.width>=140
                        onPaint: {
                            var c=getContext("2d");c.clearRect(0,0,width,height);c.strokeStyle=tab.active ? navigation.activeInk : Theme.muted;c.lineWidth=1.4;c.lineCap="round";c.lineJoin="round";
                            if(tab.modelData.glyph==="apps") {c.strokeRect(1.5,1.5,4,4);c.strokeRect(10.5,1.5,4,4);c.strokeRect(1.5,10.5,4,4);c.strokeRect(10.5,10.5,4,4);}
                            else if(tab.modelData.glyph==="windows") {c.strokeRect(1.5,5,10,9);c.beginPath();c.moveTo(5,2);c.lineTo(14.5,2);c.lineTo(14.5,10.5);c.stroke();}
                            else {c.beginPath();c.moveTo(8,1);c.lineTo(10,6);c.lineTo(15,8);c.lineTo(10,10);c.lineTo(8,15);c.lineTo(6,10);c.lineTo(1,8);c.lineTo(6,6);c.closePath();c.stroke();}
                        }
                        Connections { target: tab;function onActiveChanged(){glyph.requestPaint();} }
                        Connections { target: Orbit;function onSettingsChanged(){glyph.requestPaint();} }
                    }
                    Text {
                        width: Math.min(implicitWidth,Math.max(20,tab.width-(glyph.visible ? 24 : 0)-(badge.visible ? badge.width+8 : 0)-24))
                        text: tab.modelData.label;color: tab.active ? Theme.text : Theme.muted
                        font.pixelSize: Theme.fontSize(12);font.weight: tab.active ? Font.DemiBold : Font.Normal
                        height: 20;verticalAlignment: Text.AlignVCenter;elide: Text.ElideRight;textFormat: Text.PlainText
                    }
                    Rectangle {
                        id: badge;visible: tab.count>0 && tab.width>=140
                        width: Math.max(22,countText.implicitWidth+12);height: 20;radius: Theme.corner(6)
                        color: Theme.raised
                        Text { id: countText;anchors.centerIn: parent;text: tab.count>999 ? "999+" : tab.count;color: Theme.faint;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText }
                    }
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter;anchors.bottom: parent.bottom
                    width: Math.min(64,parent.width-24);height: 2;radius: 1;color: navigation.activeInk;visible: tab.active
                }
                MouseArea {
                    id: hit;anchors.fill: parent;hoverEnabled: true
                    onClicked: {tab.forceActiveFocus(Qt.MouseFocusReason);navigation.activateView(tab.modelData.id);}
                }
                Accessible.name: modelData.spoken+(count>0 ? ", "+count : "")
                Accessible.role: Accessible.Button
                Accessible.checkable: true
                Accessible.checked: active
                Accessible.onPressAction: navigation.activateView(modelData.id)
            }
        }
    }
}
