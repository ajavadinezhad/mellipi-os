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
    readonly property bool fit: Orbit.appearance.taskbarLength==="fit"
    readonly property real availableLength: Math.max(0,(horizontal ? width : height)-2*inset)
    readonly property real footerLength: horizontal ? footer.width+10 : footer.height+(Theme.compact ? 8 : 12)
    readonly property real bodyLength: fit ? Math.min(availableLength,Math.ceil(spine.taskStart+spine.preferredTaskLength+8+footerLength)) : availableLength
    property string requestedFocus: ""
    function focusTaskbar(name) {
        requestedFocus=name || "";
        if(requestedFocus==="spineAllWindows"){taskOverflow.forceActiveFocus(Qt.TabFocusReason);return;}
        if(requestedFocus==="spineUtilityOverflow") {
            for(let i=0;i<utilityItems.count;++i) {
                let candidate=utilityItems.itemAt(i);
                if(candidate && candidate.objectName===name){candidate.forceActiveFocus(Qt.TabFocusReason);return;}
            }
        }
        for(let i=0;i<taskItems.count;++i) {
            let candidate=taskItems.itemAt(i);
            if(candidate && candidate.objectName===name){candidate.forceActiveFocus(Qt.TabFocusReason);return;}
        }
        home.forceActiveFocus(Qt.TabFocusReason);
    }
    readonly property rect bodyGeometry: Qt.rect(spine.x,spine.y,spine.width,spine.height)
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
    readonly property bool horizontal: frame.horizontal
    readonly property var spaces: Orbit.desktops.filter(s => !outputName || !s.output || s.output===outputName)
    readonly property int verticalSpaceHeight: Math.min(spaces.length,frame.availableLength<500 ? 2 : 4)*(Theme.compact ? 28 : 33)
    readonly property var tasks: Orbit.dockApps
    readonly property var emptyTask: ({id:"",name:"",icon:"",windows:[]})
    readonly property var emptySpace: ({id:-1,active:false})
    readonly property real iconScale: (Orbit.appearance.taskbarIconScale || 100)/100
    readonly property int appIconSize: Math.round((Theme.extraCompact ? 20 : Theme.compact ? 24 : 28)*iconScale)
    readonly property int utilityIconSize: Math.round(16*iconScale)
    readonly property int taskStart: horizontal ? workspaceColumn.x+workspaceColumn.width+10 : workspaceColumn.y+workspaceColumn.height+24
    readonly property int taskSlotWidth: horizontal ? Math.max(appIconSize+10, Theme.extraCompact ? 34 : Theme.compact ? 40 : 46) : width-10
    readonly property int taskSlotHeight: horizontal ? frame.thickness-12 : Math.max(appIconSize+8, Theme.extraCompact ? 30 : Theme.compact ? 35 : 41)
    readonly property int taskSpacing: 2
    readonly property int taskLaneLength: Math.max(0,(horizontal ? footer.x : footer.y)-taskStart-8)
    readonly property int taskSlotLength: horizontal ? taskSlotWidth : taskSlotHeight
    readonly property int overflowLength: horizontal ? 30 : 25
    readonly property int preferredTaskLength: Math.max(0,Math.min(tasks.length,10)*(taskSlotLength+taskSpacing)-taskSpacing)
        + (tasks.length>10 ? taskSpacing+overflowLength : 0)
    readonly property int fullTaskCapacity: Math.max(0,Math.min(10,Math.floor((taskLaneLength+taskSpacing)/(taskSlotLength+taskSpacing))))
    readonly property int taskCapacity: tasks.length<=fullTaskCapacity ? fullTaskCapacity
        : Math.max(0,Math.min(fullTaskCapacity,Math.floor((taskLaneLength-overflowLength)/(taskSlotLength+taskSpacing))))
    readonly property int hiddenTaskCount: Math.max(0,tasks.length-taskCapacity)
    readonly property int backgroundCount: Tray.items.length+Background.items.length+Tray.legacyCount
    function isCurrentSpace(space) {
        var workspace=Orbit.outputWorkspaces[outputName];
        return workspace!==undefined ? workspace===space.id : outputName && space.output ? space.output===outputName && space.visible : space.active;
    }
    function openPanel(name) {if(outputName)Orbit.showPanelOn(name,outputName);else Orbit.showPanel(name);}
    function switchSpace(ident) {if(outputName)Orbit.switchDesktopOn(ident,outputName);else Orbit.switchDesktop(ident);}
    function taskTooltip(item,text) {Orbit.queueItemTooltip(item,text,horizontal ? item.width/2 : edge==="right" ? 0 : item.width,horizontal ? edge==="bottom" ? 0 : item.height : item.height/2);}

    readonly property bool outlined: frame.inset > 0 || Orbit.appearance.taskbarLength === "fit"
    readonly property color edgeInk: Theme.highContrast ? Theme.controlBorder
        : Theme.legibleInk(Theme.separator, 1.8, [Theme.luminance(Theme.background)], true)
    Rectangle {
        anchors.fill: parent
        color: Theme.background
        radius: Theme.corner(12)
        border.width: spine.outlined ? 1 : 0
        border.color: spine.edgeInk
    }
    Rectangle {
        visible: !spine.outlined
        x: spine.horizontal ? Theme.corner(12) : spine.edge==="right" ? 0 : spine.width-1
        y: spine.horizontal ? spine.edge==="top" ? spine.height-1 : 0 : Theme.corner(12)
        width: spine.horizontal ? spine.width-2*Theme.corner(12) : 1;height: spine.horizontal ? 1 : spine.height-2*Theme.corner(12);color: spine.edgeInk
    }
    Rectangle {visible: frame.inset===0 && Orbit.appearance.taskbarLength!=="fit";x: spine.edge==="right" ? spine.width-3 : 0;y: Theme.corner(12);width: 3;height: spine.horizontal ? spine.height-2*Theme.corner(12) : 32;color: Theme.accentInk}
    IconButton {
        id: home;objectName: "spineHome";x: spine.horizontal ? 8 : Math.round((spine.width-38)/2);y: spine.horizontal ? Math.round((spine.height-height)/2) : 7;width: 38;height: Theme.extraCompact ? 28 : Theme.compact ? 32 : 38;padding: 2;iconName: "fold";phosphor: true;relief: true;bare: true;glyphSize: spine.utilityIconSize
        hint: "Apps, windows and actions · Super";accessibleLabel: "Open Mellipi apps, windows and actions"
        onClicked: spine.openPanel("launcher")
    }


    Item {
        id: workspaceColumn
        x: spine.horizontal ? 60 : 8;y: spine.horizontal ? 2 : Theme.compact ? 52 : 60
        width: spine.horizontal ? Math.max(30,Math.min(spine.spaces.length,4)*33-3) : spine.width-16
        height: spine.horizontal ? frame.thickness-4 : spine.verticalSpaceHeight

        ListView {
            id: spaceList;objectName: "spineWorkspaceList"
            y: spine.horizontal ? Math.round((workspaceColumn.height-height)/2) : 0
            width: workspaceColumn.width;height: spine.horizontal ? (Theme.extraCompact ? 26 : Theme.compact ? 30 : 34) : spine.verticalSpaceHeight
            orientation: spine.horizontal ? ListView.Horizontal : ListView.Vertical
            // Updating the workspace array should not recreate its buttons.
            model: spine.spaces.length;clip: true;spacing: 3;boundsBehavior: Flickable.StopAtBounds
            readonly property int activeIndex: spine.spaces.findIndex(s => spine.isCurrentSpace(s))
            Item {
                objectName: "workspaceIndicatorTrack";parent: spaceList;z: 2
                width: spine.horizontal ? 30 : 3;height: spine.horizontal ? spaceList.height : Theme.compact ? 25 : 30
                visible: spaceList.activeIndex>=0
                // Animate selection only. Scroll offsets move immediately
                // with the list instead of restarting the selection tween.
                property real selectionPosition: spaceList.activeIndex*((spine.horizontal ? 30 : Theme.compact ? 25 : 30)+spaceList.spacing)
                x: spine.horizontal ? selectionPosition-spaceList.contentX : 0
                y: spine.horizontal ? 0 : selectionPosition-spaceList.contentY
                Behavior on selectionPosition {
                    enabled: !Theme.reducedMotion && Orbit.appearance.workspaceMotion!==false
                    NumberAnimation {duration: Theme.economy ? 180 : 240;easing.bezierCurve: [1/3,0,2/3,1,1,1]}
                }
                Rectangle {
                    objectName: "workspacePositionIndicator"
                    x: spine.horizontal ? 4 : 0;y: spine.horizontal ? parent.height-3 : 4
                    width: spine.horizontal ? Math.max(1,parent.width-8) : 3;height: spine.horizontal ? 3 : Math.max(1,parent.height-8)
                    radius: 1.5;color: Theme.accentInk
                }
            }
            onActiveIndexChanged: Qt.callLater(function(){if(spaceList.activeIndex>=0)spaceList.positionViewAtIndex(spaceList.activeIndex,ListView.Contain);})
            delegate: OrbitButton {
                id: space;required property int index
                readonly property var modelData: spine.spaces[index] || spine.emptySpace
                objectName: "spineWorkspace_"+modelData.id
                readonly property bool current: spine.isCurrentSpace(modelData)
                width: spine.horizontal ? 30 : workspaceColumn.width;height: spine.horizontal ? spaceList.height : Theme.compact ? 25 : 30;padding: 2;quiet: true
                text: (modelData.id<9 ? "0" : "")+(modelData.id+1);font.pixelSize: Theme.detailSize;font.weight: space.current ? Font.DemiBold : Font.Normal
                readonly property int windowCount: Orbit.windows.filter(w => w.desktop===modelData.id && !w.transient).length
                hint: (modelData.name || "Workspace "+(modelData.id+1))+" · "+windowCount+(windowCount===1 ? " window" : " windows")
                Accessible.name: hint+(current ? ", current" : "")
                DropArea {
                    id: workspaceDrop
                    anchors.fill:parent;keys:["mellipi-workspace-window"]
                    onDropped: drop => {
                        const ident=drop.source ? drop.source.windowId : "";
                        if(ident){Orbit.moveWindow(ident,space.modelData.id+1);drop.acceptProposedAction();}
                    }
                }
                Rectangle {
                    visible:space.windowCount>0;anchors.right:parent.right;anchors.rightMargin:4
                    anchors.bottom:parent.bottom;anchors.bottomMargin:5;width:4;height:4;radius:2;color:Theme.accentInk
                }
                contentItem: Text {text: space.text;font: space.font;horizontalAlignment: Text.AlignHCenter;verticalAlignment: Text.AlignVCenter;color: space.current ? Theme.text : Theme.muted}
                background: Rectangle {
                    radius: Theme.corner(8)
                    color: workspaceDrop.containsDrag ? Theme.selectedSurface : space.hovered ? Theme.hover : space.current ? Theme.selectedSurface : "transparent"
                    border.width: space.activeFocus ? 2 : space.current && Theme.highContrast ? 1 : 0
                    border.color: space.activeFocus ? Theme.focusColor : Theme.controlBorder
                }
                onClicked: spine.switchSpace(modelData.id)
            }
        }
    }
    Rectangle {x: spine.horizontal ? spine.taskStart-9 : 14;y: spine.horizontal ? 16 : workspaceColumn.y+workspaceColumn.height+12;width: spine.horizontal ? 1 : 36;height: spine.horizontal ? 32 : 1;color: Theme.separator}

    Flow {
        id: taskColumn
        x: spine.horizontal ? spine.taskStart : 5;y: spine.horizontal ? (Theme.extraCompact ? 3 : 4) : spine.taskStart
        width: spine.horizontal ? spine.taskLaneLength : parent.width-10
        height: spine.horizontal ? frame.thickness-8 : spine.taskLaneLength
        flow: spine.horizontal ? Flow.LeftToRight : Flow.TopToBottom
        spacing: spine.taskSpacing;clip: true
        Repeater {
            id: taskItems
            // Keep buttons and textures when focus/title changes leave
            // the number of displayed slots unchanged.
            model: Math.min(spine.tasks.length,spine.taskCapacity)
            Item {
                id: task;required property int index
                readonly property var modelData: spine.tasks[index] || spine.emptyTask
                width: spine.taskSlotWidth;height: spine.taskSlotHeight
                objectName: "spineTask_"+modelData.id
                readonly property bool current: modelData.windows.some(w => w.active)
                readonly property bool running: modelData.windows.length>0
                Accessible.name: modelData.name;Accessible.role: Accessible.Button
                Accessible.description: modelData.windows.length ? modelData.windows.length+" open windows" : "Launch application"
                Accessible.onPressAction: Orbit.openTaskbarGroup(task,modelData.id)
                Rectangle {
                    anchors.fill: parent
                    radius: Theme.corner(8)
                    color: "transparent"
                    border.width: task.activeFocus ? 2 : task.current && Theme.highContrast ? 1 : 0
                    border.color: task.activeFocus ? Theme.focusColor : Theme.controlBorder
                }
                Rectangle {objectName: "spineTaskRunningIndicator_"+modelData.id;x: spine.horizontal ? (task.current ? 10 : parent.width/2-2) : 0;y: spine.horizontal ? parent.height-2 : task.current ? 9 : parent.height/2-2;width: spine.horizontal ? (task.current ? parent.width-20 : 4) : 2;height: spine.horizontal ? 2 : task.current ? 23 : 4;color: task.current ? Theme.accentInk : Theme.muted;visible: task.running}
                Image {
                    anchors.centerIn: parent
                    width: Math.min(spine.appIconSize,parent.width-4,parent.height-4);height: width
                    source: modelData.icon ? Theme.taskbarIconSource(modelData.icon, modelData.internal===true) : ""
                    sourceSize: Qt.size(Math.max(24, width*2), Math.max(24, width*2));fillMode: Image.PreserveAspectFit
                    opacity: hit.pressed ? .7 : 1
                }
                Rectangle {
                    visible: modelData.windows.length > 1
                    anchors.right: parent.right; anchors.top: parent.top
                    anchors.rightMargin: 3; anchors.topMargin: 2
                    width: Math.max(14, windowCount.implicitWidth+6); height: windowCount.implicitHeight
                    radius: Theme.corner(5); color: Theme.background
                    Text {
                        id: windowCount; anchors.centerIn: parent
                        text: modelData.windows.length > 99 ? "99+" : modelData.windows.length.toString()
                        color: Theme.accentInk; font.pixelSize: Math.round(10*Theme.textScale)
                    }
                }
                MouseArea {id: hit;anchors.fill: parent;hoverEnabled: true;acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: mouse => {if(mouse.button===Qt.RightButton){var p=Orbit.itemScreenPoint(task,mouse.x,mouse.y);Orbit.openDockContext(modelData.id,p.x,p.y);}else Orbit.openTaskbarGroup(task,modelData.id);}
                    onEntered: spine.taskTooltip(task,modelData.name)
                    onExited: Orbit.hideTooltip()
                }
                Item {
                    id: dragProxy
                    width:task.width;height:task.height
                    readonly property string windowId: task.modelData.windows.length===1 ? task.modelData.windows[0].id : ""
                    Drag.keys:["mellipi-workspace-window"]
                    Drag.supportedActions:Qt.MoveAction
                    Drag.proposedAction:Qt.MoveAction
                    Drag.hotSpot.x:width/2;Drag.hotSpot.y:height/2
                }
                DragHandler {
                    enabled: !!dragProxy.windowId
                    target:dragProxy
                    onActiveChanged: {
                        if(active)dragProxy.Drag.active=true;
                        else if(dragProxy.Drag.active) {
                            dragProxy.Drag.drop();
                            dragProxy.x=0;dragProxy.y=0;
                        }
                    }
                    onCanceled: {dragProxy.Drag.cancel();dragProxy.x=0;dragProxy.y=0;}
                }
                activeFocusOnTab: true
                Keys.onPressed:event=>{if(event.key===Qt.Key_Menu || (event.key===Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))){var p=Orbit.itemScreenPoint(task,task.width/2,task.height/2);Orbit.openDockContext(modelData.id,p.x,p.y);event.accepted=true;}}
                Keys.onReturnPressed: Orbit.openTaskbarGroup(task,modelData.id)
                Keys.onEnterPressed: Orbit.openTaskbarGroup(task,modelData.id)
                Keys.onSpacePressed: Orbit.openTaskbarGroup(task,modelData.id)
            }
        }
        OrbitButton {
            id: taskOverflow;objectName: "spineAllWindows"
            visible: spine.hiddenTaskCount>0 && spine.taskLaneLength>=spine.overflowLength
            width: spine.horizontal ? spine.overflowLength : taskColumn.width
            height: spine.horizontal ? spine.taskSlotHeight : spine.overflowLength
            text: "+"+spine.hiddenTaskCount;quiet: true
            hint: spine.hiddenTaskCount+(spine.hiddenTaskCount===1 ? " more app" : " more apps")
            Accessible.name: hint
            onClicked: Orbit.openTaskbarOverflow(taskOverflow,spine.tasks.slice(spine.taskCapacity).map(t=>t.id),false)
        }
    }
    Item {
        id: footer;objectName: "spineFooter"
        x: spine.horizontal ? spine.width-width-8 : 2
        y: spine.horizontal ? 0 : spine.height-height-6
        width: spine.horizontal ? footerIcons.width+8+clockGroup.naturalWidth : frame.thickness-4
        height: spine.horizontal ? frame.thickness : footerIcons.height+clockGroup.height+14
        Rectangle {visible: !spine.horizontal;width: parent.width;height: 1;color: Theme.separator}
        Grid {
            id: footerIcons
            x:spine.horizontal ? 0 : Math.round((footer.width-width)/2)
            y:spine.horizontal ? Math.max(0,Math.round((footer.height-height)/2)) : 4
            readonly property int buttonWidth: Math.max(24,spine.utilityIconSize+4,Theme.compact ? 24 : 30)
            readonly property int buttonHeight: buttonWidth
            readonly property int across: Math.max(1,Math.min(2,Math.floor((frame.thickness-4)/buttonWidth)))
            readonly property var primary: [{key:"music",item:"Sound",glyph:System.values.muted ? "mute" : "volume",hint:"Volume and playback"},{key:"quick",item:"Controls",glyph:"settings",hint:"Quick controls"}]
            readonly property var secondary: [
                {key:"screenshot",item:"Capture",glyph:"camera",hint:"Screenshot"},
                {key:"notifications",item:"Notifications",glyph:"bell",hint:"Notifications"},
                {key:"tray",item:"Background",glyph:spine.edge==="left" ? "chevron-right" : spine.edge==="right" ? "chevron-left" : spine.edge==="top" ? "chevron-down" : "chevron-up",hint:"Background apps"},
                {key:"usage",item:"Usage",glyph:"usage",hint:"System Monitor"}
            ].concat(Orbit.nativePlacementSupported===true ? [{key:"window-placement",item:"AutoSnap",glyph:"start-spaces",hint:"Auto-snap · "+(Orbit.windowPlacementEnabled ? "On" : "Off")}] : [])
            readonly property int capacity: spine.horizontal ?
                Math.max(3,Math.floor((frame.availableLength-spine.taskStart-clockGroup.naturalWidth-88)/buttonWidth)) :
                Math.max(3,across*Math.floor((frame.availableLength-spine.taskStart-clockGroup.height-88)/buttonHeight))
            readonly property int shownSecondary: Math.max(0,Math.min(secondary.length,capacity-primary.length-
                (secondary.length+primary.length>capacity ? 1 : 0)))
            readonly property var hidden: secondary.slice(shownSecondary)
            readonly property var visibleItems: secondary.slice(0,shownSecondary).concat(primary,hidden.length ?
                [{key:"overflow",item:"UtilityOverflow",glyph:"more",hint:"More taskbar controls"}] : [])
            columns:spine.horizontal ? visibleItems.length : across
            spacing:0
            Repeater {
                id:utilityItems;model:footerIcons.visibleItems
                IconButton {
                    id:control;required property var modelData
                    objectName:"spine"+modelData.item
                    phosphor:true;relief:true;bare:true;glyphSize:spine.utilityIconSize
                    width:footerIcons.buttonWidth;height:footerIcons.buttonHeight;padding:2
                    glyphColor:modelData.key==="window-placement" && !Orbit.windowPlacementEnabled ? Theme.muted : Theme.accentInk
                    accent:Orbit.panel===modelData.key
                    iconName:modelData.glyph;hint:modelData.hint
                    onClicked:{
                        if(modelData.key==="usage")Orbit.openSystemMonitor();
                        else if(modelData.key==="overflow")Orbit.openTaskbarOverflow(control,footerIcons.hidden.map(r=>r.key),true);
                        else spine.openPanel(modelData.key);
                    }
                    Rectangle {
                        visible:control.modelData.key==="notifications" && System.notifications.length>0
                        x:Math.round(parent.width/2)+6;y:Math.max(2,Math.round(parent.height/2)-9)
                        width:4;height:4;radius:2;color:Theme.accentInk
                    }
                }
            }
        }
        FontMetrics {id: clockMetrics;font: clockLabel.font}
        FontMetrics {id: dateMetrics;font: dateLabel.font}
        FontMetrics {id: batteryMetrics;font: batteryLabel.font}
        Rectangle {
            anchors.fill: clockGroup
            anchors.margins: -2
            radius: Theme.corner(6)
            color: clockHit.containsMouse ? Theme.hover : "transparent"
            border.width: clockGroup.activeFocus ? 2 : 0
            border.color: Theme.focusColor
        }
        MouseArea {
            id: clockHit
            anchors.fill: clockGroup
            hoverEnabled: true
            z: 1
            cursorShape: Qt.PointingHandCursor
            onClicked: Orbit.launch("mellipi-calendar.desktop")
        }
        Column {
            id: clockGroup;x: spine.horizontal ? footerIcons.width+10 : (parent.width-width)/2;y: spine.horizontal ? Math.round((frame.thickness-height)/2) : footerIcons.y+footerIcons.height+6
            readonly property int naturalWidth: Math.ceil(Math.max(clockMetrics.advanceWidth(clockLabel.text),dateLabel.visible ? dateMetrics.advanceWidth(dateLabel.text) : 0,batteryLabel.visible ? batteryMetrics.advanceWidth(batteryLabel.text) : 0))+8
            readonly property string batteryText: Power.state.batteryPresent || System.values.batteryPresent
                ? (Power.state.percentageAvailable ? Power.state.batteryPercent : System.values.batteryPercent)+"%" : ""
            readonly property string dateText: Orbit.appearance.clockDate ? Qt.formatDateTime(spine.clockNow,"MMM d") : ""
            width: spine.horizontal ? naturalWidth : spine.width-4;spacing: 2
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: "Open Calendar"
            Accessible.description: [clockLabel.text, dateText, batteryText].filter(Boolean).join(" · ")
            Accessible.onPressAction: Orbit.launch("mellipi-calendar.desktop")
            Keys.onReturnPressed: Orbit.launch("mellipi-calendar.desktop")
            Keys.onSpacePressed: Orbit.launch("mellipi-calendar.desktop")
            Text {id: clockLabel;width: parent.width;fontSizeMode: spine.horizontal ? Text.FixedSize : Text.HorizontalFit;minimumPixelSize: 8;text: spine.horizontal && !Orbit.appearance.clock24 ? spine.clockText+" "+Qt.formatDateTime(spine.clockNow,"AP") : spine.clockText;font.pixelSize: Theme.detailSize;font.weight: Font.DemiBold;color: Theme.text;horizontalAlignment: Text.AlignHCenter;elide: Text.ElideRight}
            Text {width: parent.width;visible: !spine.horizontal && !Orbit.appearance.clock24;text: Qt.formatDateTime(spine.clockNow,"AP");font.pixelSize: Math.round(10*Theme.textScale);color: Theme.muted;horizontalAlignment: Text.AlignHCenter}
            Text {
                id: dateLabel
                width: parent.width
                fontSizeMode: spine.horizontal ? Text.FixedSize : Text.HorizontalFit
                minimumPixelSize: 8
                visible: text.length > 0
                text: spine.horizontal ? [clockGroup.dateText,clockGroup.batteryText].filter(Boolean).join(" · ") : clockGroup.dateText
                font.pixelSize: Math.round(10*Theme.textScale)
                color: Theme.muted
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
            Text {
                id: batteryLabel
                width: parent.width
                text: clockGroup.batteryText
                visible: !spine.horizontal && text.length > 0
                font.pixelSize: Math.round(10*Theme.textScale)
                color: Theme.muted
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
}

}
