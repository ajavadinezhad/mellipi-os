import QtQuick 2.15
import "."

Item {
    id: frame
    property string outputName: ""
    property string clockText: ""
    property date clockNow: new Date()
    readonly property bool horizontal: Orbit.appearance.panelPosition==="top" || Orbit.appearance.panelPosition==="bottom"
    readonly property int thickness: Theme.barThickness
    readonly property real inset: Orbit.appearance.taskbarFloating ? 8 : 0
    readonly property int taskCount: Orbit.dockApps.length
    readonly property real fitLength: horizontal ? (Theme.extraCompact ? 480 : Theme.compact ? 560 : 640)+Math.min(8,taskCount)*(Theme.extraCompact ? 59 : Theme.compact ? 67 : 79) : (Theme.extraCompact ? 420 : Theme.compact ? 480 : 550)+Math.min(8,taskCount)*(Theme.extraCompact ? 38 : Theme.compact ? 46 : 55)
    readonly property real bodyLength: Math.min((horizontal ? width : height)-2*inset,Orbit.appearance.taskbarLength==="fit" ? fitLength : (horizontal ? width : height)-2*inset)
    Item {

    id: spine
    objectName: "orbitSpine"
    x: frame.horizontal ? Math.floor((frame.width-frame.bodyLength)/2) : frame.inset
    y: frame.horizontal ? frame.inset : Math.floor((frame.height-frame.bodyLength)/2)
    width: frame.horizontal ? frame.bodyLength : frame.thickness
    height: frame.horizontal ? frame.thickness : frame.bodyLength
    implicitWidth: horizontal ? 640 : 64
    implicitHeight: horizontal ? 64 : 640
    property string outputName: frame.outputName
    property string clockText: frame.clockText
    property date clockNow: frame.clockNow
    readonly property string edge: Orbit.appearance.panelPosition || "left"
    readonly property bool horizontal: edge==="top" || edge==="bottom"
    readonly property bool denseFooter: horizontal && (Orbit.appearance.taskbarLength==="fit" || width<850)
    readonly property var spaces: Orbit.desktops.filter(s => !outputName || !s.output || s.output===outputName)
    readonly property var tasks: Orbit.dockApps
    readonly property int taskStart: horizontal ? workspaceColumn.x+workspaceColumn.width+16 : workspaceColumn.y+workspaceColumn.height+40
    readonly property int taskSlotWidth: horizontal ? (Theme.extraCompact ? 56 : Theme.compact ? 64 : 76) : width-10
    readonly property int taskSlotHeight: horizontal ? frame.thickness-12 : Theme.extraCompact ? 35 : Theme.compact ? 43 : 52
    readonly property int taskSpacing: 3
    readonly property int taskLaneLength: Math.max(0,(horizontal ? footer.x : footer.y)-taskStart-8)
    readonly property int taskSlotLength: horizontal ? taskSlotWidth : taskSlotHeight
    readonly property int overflowLength: horizontal ? 30 : 25
    readonly property int fullTaskCapacity: Math.max(0,Math.min(10,Math.floor((taskLaneLength+taskSpacing)/(taskSlotLength+taskSpacing))))
    readonly property int taskCapacity: tasks.length<=fullTaskCapacity ? fullTaskCapacity
        : Math.max(0,Math.min(fullTaskCapacity,Math.floor((taskLaneLength-overflowLength)/(taskSlotLength+taskSpacing))))
    readonly property int hiddenTaskCount: Math.max(0,tasks.length-taskCapacity)
    readonly property int backgroundCount: Tray.items.length+Background.items.length+Tray.legacyCount
    function isCurrentSpace(space) {return outputName && space.output ? space.output===outputName && space.visible : space.active;}
    function openPanel(name) {if(outputName)Orbit.showPanelOn(name,outputName);else Orbit.showPanel(name);}
    function switchSpace(ident) {if(outputName)Orbit.switchDesktopOn(ident,outputName);else Orbit.switchDesktop(ident);}
    function taskTooltip(item,text) {Orbit.queueItemTooltip(item,text,horizontal ? item.width/2 : edge==="right" ? 0 : item.width,horizontal ? edge==="bottom" ? 0 : item.height : item.height/2);}

    Rectangle {anchors.fill: parent;color: Theme.background;radius: Theme.corner(12);border.width:frame.inset>0 ? Theme.surfaceOutline : 0;border.color:Theme.border}
    Rectangle {
        visible: frame.inset===0 && Orbit.appearance.taskbarLength!=="fit"
        x: spine.horizontal ? Theme.corner(12) : spine.edge==="right" ? 0 : spine.width-1
        y: spine.horizontal ? spine.edge==="top" ? spine.height-1 : 0 : Theme.corner(12)
        width: spine.horizontal ? spine.width-2*Theme.corner(12) : 1;height: spine.horizontal ? 1 : spine.height-2*Theme.corner(12);color: Theme.separator
    }
    Rectangle {visible: frame.inset===0 && Orbit.appearance.taskbarLength!=="fit";x: spine.edge==="right" ? spine.width-3 : 0;y: Theme.corner(12);width: 3;height: spine.horizontal ? spine.height-2*Theme.corner(12) : 32;color: Theme.accent}
    IconButton {
        id: home;objectName: "spineHome";x: spine.horizontal ? 8 : Math.round((spine.width-38)/2);y: spine.horizontal ? (Theme.extraCompact ? 2 : 4) : 7;width: 38;height: Theme.extraCompact ? 26 : Theme.compact ? 32 : 38;iconName: "fold"
        hint: "Apps, windows and actions · Super";accessibleLabel: "Open Mellipi apps, windows and actions"
        onClicked: spine.openPanel("launcher")
    }
    Text {x: spine.horizontal ? 3 : Math.round((spine.width-50)/2);y: spine.horizontal ? (Theme.extraCompact ? 28 : Theme.compact ? 35 : 43) : 45;width: 50;height: 16;text: "Mellipi";font.pixelSize: Theme.fontSize(8);font.letterSpacing: 0;fontSizeMode: Text.HorizontalFit;minimumPixelSize: 7;horizontalAlignment: Text.AlignHCenter;color: Theme.muted;elide: Text.ElideRight}

    Item {
        id: workspaceColumn
        x: spine.horizontal ? 60 : 8;y: spine.horizontal ? 2 : Theme.compact ? 70 : 76
        width: spine.horizontal ? Math.max(30,Math.min(spine.spaces.length,4)*33-3) : spine.width-16
        height: spine.horizontal ? frame.thickness-4 : spaceList.y+spaceList.height
        Text {width: parent.width;height:14;text: "SPACE";font.pixelSize: Theme.fontSize(8);font.letterSpacing: .8;color: Theme.faint;horizontalAlignment: Text.AlignHCenter}
        ListView {
            id: spaceList;objectName: "spineWorkspaceList"
            y: spine.horizontal ? (Theme.extraCompact ? 16 : Theme.compact ? 21 : 29) : 17
            width: workspaceColumn.width;height: spine.horizontal ? (Theme.extraCompact ? 26 : Theme.compact ? 30 : 34) : Math.min(count,spine.height<500 ? 2 : 4)*(Theme.compact ? 28 : 33)
            orientation: spine.horizontal ? ListView.Horizontal : ListView.Vertical
            model: spine.spaces;clip: true;spacing: 3;boundsBehavior: Flickable.StopAtBounds
            readonly property int activeIndex: spine.spaces.findIndex(s => spine.isCurrentSpace(s))
            Item {
                objectName: "workspaceIndicatorTrack";parent: spaceList;z: 2
                width: spine.horizontal ? 30 : 3;height: spine.horizontal ? spaceList.height : Theme.compact ? 25 : 30
                visible: spaceList.activeIndex>=0
                x: spine.horizontal ? spaceList.activeIndex*(30+spaceList.spacing)-spaceList.contentX : 0
                y: spine.horizontal ? 0 : spaceList.activeIndex*((Theme.compact ? 25 : 30)+spaceList.spacing)-spaceList.contentY
                Behavior on x {NumberAnimation {duration: Theme.reducedMotion || Orbit.appearance.workspaceMotion===false ? 0 : Theme.economy ? 180 : 240;easing.bezierCurve: [1/3,0,2/3,1,1,1]}}
                Behavior on y {NumberAnimation {duration: Theme.reducedMotion || Orbit.appearance.workspaceMotion===false ? 0 : Theme.economy ? 180 : 240;easing.bezierCurve: [1/3,0,2/3,1,1,1]}}
                Rectangle {
                    objectName: "workspacePositionIndicator"
                    x: spine.horizontal ? 4 : 0;y: spine.horizontal ? parent.height-3 : 4
                    width: spine.horizontal ? Math.max(1,parent.width-8) : 3;height: spine.horizontal ? 3 : Math.max(1,parent.height-8)
                    radius: 1.5;color: Theme.accent
                }
            }
            onActiveIndexChanged: Qt.callLater(function(){if(spaceList.activeIndex>=0)spaceList.positionViewAtIndex(spaceList.activeIndex,ListView.Contain);})
            delegate: OrbitButton {
                id: space;required property var modelData
                objectName: "spineWorkspace_"+modelData.id
                readonly property bool current: spine.isCurrentSpace(modelData)
                width: spine.horizontal ? 30 : workspaceColumn.width;height: spine.horizontal ? spaceList.height : Theme.compact ? 25 : 30;padding: 2;quiet: true
                text: (modelData.id<9 ? "0" : "")+(modelData.id+1);font.pixelSize: Theme.fontSize(11)
                hint: "Workspace "+(modelData.id+1);Accessible.name: hint+(current ? ", current" : "")
                contentItem: Text {text: space.text;font: space.font;horizontalAlignment: Text.AlignHCenter;verticalAlignment: Text.AlignVCenter;color: space.current ? Theme.text : Theme.faint}
                background: Rectangle {radius:Theme.corner(10);color: space.hovered || space.activeFocus ? Theme.hover : "transparent"}
                onClicked: spine.switchSpace(modelData.id)
            }
        }
    }
    Rectangle {x: spine.horizontal ? spine.taskStart-9 : 14;y: spine.horizontal ? 16 : workspaceColumn.y+workspaceColumn.height+12;width: spine.horizontal ? 1 : 36;height: spine.horizontal ? 32 : 1;color: Theme.separator}
    Text {visible: !spine.horizontal;x: 8;y: workspaceColumn.y+workspaceColumn.height+23;width: parent.width-16;text: spine.tasks.filter(a=>a.windows.length>0).length+" OPEN";font.pixelSize: Theme.fontSize(8);font.letterSpacing: .6;color: Theme.faint;horizontalAlignment: Text.AlignHCenter}
    Flow {
        id: taskColumn
        x: spine.horizontal ? spine.taskStart : 5;y: spine.horizontal ? (Theme.extraCompact ? 3 : 4) : spine.taskStart
        width: spine.horizontal ? spine.taskLaneLength : parent.width-10
        height: spine.horizontal ? frame.thickness-8 : spine.taskLaneLength
        flow: spine.horizontal ? Flow.LeftToRight : Flow.TopToBottom
        spacing: spine.taskSpacing;clip: true
        Repeater {
            model: spine.tasks.slice(0,spine.taskCapacity)
            Item {
                id: task;required property var modelData;width: spine.taskSlotWidth;height: spine.taskSlotHeight
                objectName: "spineTask_"+modelData.id
                readonly property bool current: modelData.windows.some(w => w.active)
                readonly property bool running: modelData.windows.length>0
                Accessible.name: modelData.name;Accessible.role: Accessible.Button
                Accessible.description: modelData.windows.length ? modelData.windows.length+" open windows" : "Launch application"
                Accessible.onPressAction: Orbit.activateDock(modelData.id,false)
                Rectangle {anchors.fill: parent;radius:Theme.corner(10);color: hit.containsMouse || task.activeFocus ? Theme.hover : "transparent";border.color: task.activeFocus ? Theme.focusColor : "transparent"}
                Rectangle {objectName: "spineTaskRunningIndicator_"+modelData.id;x: spine.horizontal ? (task.current ? 10 : parent.width/2-2) : 0;y: spine.horizontal ? parent.height-2 : task.current ? 9 : parent.height/2-2;width: spine.horizontal ? (task.current ? parent.width-20 : 4) : 2;height: spine.horizontal ? 2 : task.current ? 23 : 4;color: task.current ? Theme.accent : Theme.muted;visible: task.running}
                Image {x: Math.round((parent.width-(Theme.extraCompact ? 20 : Theme.compact ? 24 : 28))/2);y: spine.horizontal ? (Theme.extraCompact ? 2 : 4) : 3;width: Theme.extraCompact ? 20 : Theme.compact ? 24 : 28;height: width;source: Theme.iconSource(modelData.icon);sourceSize: Qt.size(32,32);fillMode: Image.PreserveAspectFit}
                Text {x: 3;y: spine.horizontal ? (Theme.extraCompact ? 25 : Theme.compact ? 31 : 39) : Theme.extraCompact ? 25 : 29;width: parent.width-6;text: modelData.name;font.pixelSize: Theme.fontSize(8);color: task.current ? Theme.text : Theme.faint;elide: Text.ElideRight;horizontalAlignment: Text.AlignHCenter;textFormat: Text.PlainText}
                Text {anchors.right: parent.right;anchors.top: parent.top;anchors.rightMargin: 3;text: modelData.windows.length>1 ? modelData.windows.length : "";color: Theme.accent;font.pixelSize: Theme.fontSize(8)}
                MouseArea {id: hit;anchors.fill: parent;hoverEnabled: true;acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: mouse => {if(mouse.button===Qt.RightButton){var p=Orbit.itemScreenPoint(task,mouse.x,mouse.y);Orbit.openDockContext(modelData.id,p.x,p.y);}else Orbit.activateDock(modelData.id,false);}
                    onEntered: spine.taskTooltip(task,modelData.name)
                    onExited: Orbit.hideTooltip()
                }
                activeFocusOnTab: true
                Keys.onPressed:event=>{if(event.key===Qt.Key_Menu || (event.key===Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))){var p=Orbit.itemScreenPoint(task,task.width/2,task.height/2);Orbit.openDockContext(modelData.id,p.x,p.y);event.accepted=true;}}
                Keys.onReturnPressed: Orbit.activateDock(modelData.id,false)
                Keys.onEnterPressed: Orbit.activateDock(modelData.id,false)
                Keys.onSpacePressed: Orbit.activateDock(modelData.id,false)
            }
        }
        OrbitButton {
            objectName: "spineAllWindows"
            visible: spine.hiddenTaskCount>0 && spine.taskLaneLength>=spine.overflowLength
            width: spine.horizontal ? spine.overflowLength : taskColumn.width
            height: spine.horizontal ? spine.taskSlotHeight : spine.overflowLength
            text: "+"+spine.hiddenTaskCount;quiet: true
            hint: spine.hiddenTaskCount+(spine.hiddenTaskCount===1 ? " more app" : " more apps")
            Accessible.name: hint
            onClicked: spine.openPanel("overview")
        }
    }
    Item {
        id: footer;objectName: "spineFooter"
        x: spine.horizontal ? spine.width-width-10 : Theme.extraCompact ? 6 : 8;y: spine.horizontal ? 0 : spine.height-height-(Theme.compact ? 8 : 12)
        width: spine.horizontal ? spine.denseFooter ? (Theme.extraCompact ? 150 : Theme.compact ? 174 : 198) : (Theme.compact ? 290 : 320) : spine.width-(Theme.extraCompact ? 12 : 16)
        height: spine.horizontal ? frame.thickness : footerIcons.height+clockGroup.height+18
        Rectangle {visible: !spine.horizontal;width: parent.width;height: 1;color: Theme.separator}
        Grid {
            id: footerIcons;x: 0;y: spine.horizontal ? Math.max(0,Math.round((footer.height-height)/2)) : 6
            columns: spine.horizontal ? spine.denseFooter ? 3 : 6 : 2;spacing: 0
            readonly property int buttonWidth: spine.horizontal ? (Theme.extraCompact ? 22 : Theme.compact ? 28 : 32) : Math.floor(footer.width/2)
            readonly property int buttonHeight: spine.horizontal ? buttonWidth : Theme.extraCompact ? 24 : Theme.compact ? 27 : 32
            readonly property color iconInk: Theme.highContrast ? Theme.text : Theme.accent
            IconButton {objectName: "spineCapture";width: footerIcons.buttonWidth;height: footerIcons.buttonHeight;padding: Theme.extraCompact ? 2 : 4;glyphColor: footerIcons.iconInk;iconName: "camera";hint: "Screenshot";onClicked: spine.openPanel("screenshot")}
            IconButton {objectName: "spineNotifications";width: footerIcons.buttonWidth;height: footerIcons.buttonHeight;padding: Theme.extraCompact ? 2 : 4;glyphColor: footerIcons.iconInk;iconName: "bell";hint: "Notifications";onClicked: spine.openPanel("notifications")
                Rectangle {x: Math.round(parent.width/2)+6;y: Math.max(2,Math.round(parent.height/2)-9);width: 4;height: 4;radius: 2;color: Theme.accent;visible: System.notifications.length>0}
            }
            IconButton {objectName: "spineSound";width: footerIcons.buttonWidth;height: footerIcons.buttonHeight;padding: Theme.extraCompact ? 2 : 4;glyphColor: footerIcons.iconInk;iconName: System.values.muted ? "mute" : "volume";hint: "Volume and playback";onClicked: spine.openPanel("music")}
            IconButton {objectName: "spineBackground";width: footerIcons.buttonWidth;height: footerIcons.buttonHeight;padding: Theme.extraCompact ? 2 : 4;glyphColor: footerIcons.iconInk;iconName: spine.edge==="left" ? "chevron-right" : spine.edge==="right" ? "chevron-left" : spine.edge==="top" ? "chevron-down" : "chevron-up";hint: "Background apps";onClicked: spine.openPanel("tray")}
            IconButton {objectName: "spineUsage";width: footerIcons.buttonWidth;height: footerIcons.buttonHeight;padding: Theme.extraCompact ? 2 : 4;glyphColor: footerIcons.iconInk;iconName: "usage";hint: "System usage · "+Usage.username;onClicked: spine.openPanel("usage")}
            IconButton {objectName: "spineControls";width: footerIcons.buttonWidth;height: footerIcons.buttonHeight;padding: Theme.extraCompact ? 2 : 4;glyphColor: footerIcons.iconInk;iconName: "settings";hint: "Quick controls";onClicked: spine.openPanel("quick")}
        }
        Column {
            id: clockGroup;x: spine.horizontal ? footerIcons.width+10 : 0;y: spine.horizontal ? Math.round((frame.thickness-height)/2) : footerIcons.y+footerIcons.height+6
            width: spine.horizontal ? parent.width-x : parent.width;spacing: 2
            Text {width: parent.width;text: spine.horizontal && !Orbit.appearance.clock24 ? spine.clockText+" "+Qt.formatDateTime(spine.clockNow,"AP") : spine.clockText;font.pixelSize: Theme.fontSize(10);color: Theme.text;horizontalAlignment: Text.AlignHCenter;elide: Text.ElideRight}
            Text {width: parent.width;visible: !spine.horizontal && !Orbit.appearance.clock24;text: Qt.formatDateTime(spine.clockNow,"AP");font.pixelSize: Theme.fontSize(8);color: Theme.muted;horizontalAlignment: Text.AlignHCenter}
            Text {width: parent.width;visible: !!Orbit.appearance.clockDate;text: Qt.formatDateTime(spine.clockNow,"MMM d");font.pixelSize: Theme.fontSize(8);color: Theme.muted;horizontalAlignment: Text.AlignHCenter}
            Text {width: parent.width;text: Power.state.batteryPresent || System.values.batteryPresent ? (Power.state.percentageAvailable ? Power.state.batteryPercent : System.values.batteryPercent)+"%" : "";visible: text.length>0;font.pixelSize: Theme.fontSize(9);color: Theme.muted;horizontalAlignment: Text.AlignHCenter}
        }
    }
}

}
