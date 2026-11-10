import QtQuick 2.15
import "."

Item {
    id: perimeter
    objectName: "foldTopbar"
    property string clockText: ""
    property int screenWidth: width
    property string outputName: ""
    function openPanel(name){if(outputName)Orbit.showPanelOn(name,outputName);else Orbit.showPanel(name);}
    function switchSpace(ident){if(outputName)Orbit.switchDesktopOn(ident,outputName);else Orbit.switchDesktop(ident);}
    readonly property bool connected: Orbit.appearance.topbarConnected === true
    readonly property int controlHeight: Theme.compact ? 24 : 30
    readonly property int iconWidth: screenWidth<700 ? 24 : 28
    readonly property var spaces: {
        var result=Orbit.desktops.filter(space => !perimeter.outputName || !space.output || space.output===perimeter.outputName).slice(0,screenWidth<700 ? 4 : 8);
        var active=Orbit.desktops.find(space => space.active);
        if(active && result.length && !result.some(space => space.id===active.id))result[result.length-1]=active;
        return result;
    }
    readonly property string shortClock: clockText.indexOf("·")>=0 ? clockText.split("·").pop().trim() : clockText
    readonly property int backgroundCount: Tray.items.length+Background.items.length+Tray.legacyCount
    readonly property bool batteryPresent: Power.state.batteryPresent || System.values.batteryPresent
    readonly property string batteryText: Power.state.percentageAvailable ? Power.state.batteryPercent+"%" : System.values.batteryPresent ? System.values.batteryPercent+"%" : "Battery"

    Rectangle {
        objectName: "foldTopConnectedStrip"
        x: 6;y: 2;width: parent.width-12;height: parent ? parent.height-4 : 0
        visible: perimeter.connected;color: Theme.background;border.color: Theme.border;radius: 0
    }

    Rectangle {
        id: leftPaper;objectName: "foldTopLeft"
        x: 6;y: 2;width: leftRow.width+12;height: parent ? parent.height-4 : 0
        color: perimeter.connected ? "transparent" : Theme.background;border.color: Theme.border;border.width: perimeter.connected ? 0 : 1;radius: 0
        Row {
            id: leftRow;anchors.centerIn: parent;spacing: 8
            IconButton {padding: 4;
                objectName: "foldTopBrand";iconName: "fold";implicitWidth: 25;implicitHeight: perimeter.controlHeight
                hint: "Unfold Mellipi · Super";onClicked: perimeter.openPanel("launcher")
            }
            Text {
                text: "MELLIPI";height: perimeter.controlHeight;verticalAlignment: Text.AlignVCenter
                color: Theme.text;font.pixelSize: Theme.fontSize(10);font.letterSpacing: 1.3
                visible: perimeter.screenWidth>=700
            }
            Rectangle {width: 1;height: 12;anchors.verticalCenter: parent ? parent.verticalCenter : undefined;color: Theme.border}
            Row {
                objectName: "foldWorkspaceIndicators";spacing: 2
                Repeater {
                    model: perimeter.spaces
                    OrbitButton {
                        required property var modelData
                        objectName: "foldWorkspace_"+modelData.id
                        text: String(modelData.id+1);quiet: true;implicitWidth: 23;implicitHeight: perimeter.controlHeight;padding: 2
                        font.pixelSize: Theme.fontSize(11);hint: "Switch to "+(modelData.name===String(modelData.id+1) ? "workspace "+(modelData.id+1) : modelData.name)
                        Accessible.name: hint
                        background: Item {
                            Rectangle {anchors.fill: parent;color: parent.parent.hovered ? Theme.hover : "transparent"}
                            Rectangle {anchors.horizontalCenter: parent ? parent.horizontalCenter : undefined;anchors.bottom: parent ? parent.bottom : undefined;width: 13;height: 1;color: Theme.accent;visible: perimeter.outputName ? (modelData.output===perimeter.outputName && modelData.visible) : modelData.active}
                        }
                        onClicked: perimeter.switchSpace(modelData.id)
                    }
                }
            }
        }
        Rectangle {anchors.left: parent ? parent.left : undefined;anchors.bottom: parent ? parent.bottom : undefined;width: 15;height: 1;color: Theme.accent}
    }

    Item {
        id: clockPaper;objectName: "foldTopClock"
        anchors.horizontalCenter: parent ? parent.horizontalCenter : undefined;y: 2;height: parent ? parent.height-4 : 0
        width: Math.max(0,Math.min(clock.implicitWidth+24,perimeter.width-2*Math.max(leftPaper.width+6,rightPaper.width+6)-16))
        visible: width>=48
        Rectangle {anchors.fill: parent;color: perimeter.connected ? "transparent" : Theme.background}
        Text {
            id: clock;anchors.centerIn: parent;width: Math.max(1,parent.width-12)
            text: perimeter.screenWidth>=1000 ? perimeter.clockText : perimeter.shortClock
            horizontalAlignment: Text.AlignHCenter;elide: Text.ElideRight;textFormat: Text.PlainText
            color: Theme.text;font.pixelSize: Theme.fontSize(11)
        }
        Rectangle {anchors.horizontalCenter: parent ? parent.horizontalCenter : undefined;anchors.bottom: parent ? parent.bottom : undefined;width: 12;height: 1;color: Theme.accent;opacity: .8}
    }

    Rectangle {
        id: rightPaper;objectName: "foldTopRight"
        anchors.right: parent ? parent.right : undefined;anchors.rightMargin: 6;y: 2
        width: rightRow.width+12;height: parent ? parent.height-4 : 0;color: perimeter.connected ? "transparent" : Theme.background;border.color: Theme.border;border.width: perimeter.connected ? 0 : 1;radius: 0
        Row {
            id: rightRow;anchors.centerIn: parent;spacing: perimeter.screenWidth<700 ? 2 : 4
            IconButton {padding: 4;objectName: "foldTopCamera";iconName: "camera";implicitWidth: perimeter.iconWidth;implicitHeight: perimeter.controlHeight;hint: "Screenshot · Print Screen";onClicked: perimeter.openPanel("screenshot")}
            IconButton {padding: 4;objectName: "foldTopMusic";iconName: System.values.muted ? "mute" : "volume";implicitWidth: perimeter.iconWidth;implicitHeight: perimeter.controlHeight;hint: "Music and sound"+(System.values.audioAvailable ? " · "+System.values.volume+"%" : "");onClicked: perimeter.openPanel("music")}
            Rectangle {width: 1;height: 12;anchors.verticalCenter: parent ? parent.verticalCenter : undefined;color: Theme.border}
            IconButton {padding: 4;objectName: "foldTopNotifications";iconName: "bell";implicitWidth: perimeter.iconWidth;implicitHeight: perimeter.controlHeight;hint: "Notifications"+(System.notifications.length ? " · "+System.notifications.length : "");onClicked: perimeter.openPanel("notifications")
                Rectangle {anchors.right: parent ? parent.right : undefined;anchors.top: parent ? parent.top : undefined;anchors.margins: 2;width: 3;height: 3;color: Theme.accent;visible: System.notifications.length>0}
            }
            IconButton {padding: 4;objectName: "foldTopBackground";iconName: Orbit.panel==="tray" ? "chevron-up" : "chevron-down";implicitWidth: perimeter.iconWidth;implicitHeight: perimeter.controlHeight;visible: perimeter.backgroundCount>0;hint: "Background apps · "+perimeter.backgroundCount;onClicked: perimeter.openPanel("tray")}
            Rectangle {width: 1;height: 12;anchors.verticalCenter: parent ? parent.verticalCenter : undefined;color: Theme.border}
            OrbitButton {objectName: "foldTopBattery";text: perimeter.batteryText;quiet: true;visible: perimeter.batteryPresent;implicitHeight: perimeter.controlHeight;implicitWidth: Math.max(38,contentItem.implicitWidth+8);padding: 3;font.pixelSize: Theme.fontSize(10);hint: "Battery and charging limit";Accessible.name: hint+" · "+text;onClicked: perimeter.openPanel("battery")}
            IconButton {padding: 4;objectName: "foldTopUsage";iconName: "usage";implicitWidth: perimeter.iconWidth;implicitHeight: perimeter.controlHeight;hint: "System usage · Signed in as "+Usage.username;onClicked: perimeter.openPanel("usage")}
            OrbitButton {text: Usage.username;quiet: true;visible: perimeter.screenWidth>=1000;implicitWidth: Math.min(70,contentItem.implicitWidth+8);implicitHeight: perimeter.controlHeight;padding: 3;font.pixelSize: Theme.fontSize(10);hint: "Signed in as "+Usage.username;onClicked: perimeter.openPanel("usage")}
            IconButton {padding: 4;objectName: "foldTopSettings";iconName: "settings";implicitWidth: perimeter.iconWidth;implicitHeight: perimeter.controlHeight;hint: "Quick settings";onClicked: perimeter.openPanel("quick")}
        }
        Rectangle {anchors.right: parent ? parent.right : undefined;anchors.bottom: parent ? parent.bottom : undefined;width: 15;height: 1;color: Theme.accent}
    }
}
