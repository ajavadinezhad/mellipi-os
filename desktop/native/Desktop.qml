import QtQuick 2.15
import "."
import "ClockFormat.js" as ClockFormat
import QtQml 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

QtObject {
    id: shell
    property string renderedPanel: ""
    property bool overlayShown: false
    property int sw: Orbit.screenGeometry.width
    property int sh: Orbit.screenGeometry.height
    property int sx: Orbit.screenGeometry.x
    property int sy: Orbit.screenGeometry.y
    property date clockNow: new Date()
    property string clock: Qt.formatDateTime(clockNow,(Orbit.appearance.clockDate && shell.sw>=1000 ? "ddd, MMM d   ·   " : "")+(Orbit.appearance.clock24 ? "HH:mm" : "h:mm AP"))
    property string hour: Qt.formatDateTime(new Date(), "hh:mm")
    property string query: ""
    property string launchTab: "Apps"
    property bool launchPinned: false
    property int dockCapacity: Orbit.dockGeometry.capacity
    property var visibleWindows: Orbit.windowFilter.length ? Orbit.windows.filter(w => Orbit.windowFilter.indexOf(w.id)>=0) : Orbit.windows
    property int workspacePanelWidth: Math.min(760,sw-32)
    property bool workPanel: ["launcher","overview","ai"].indexOf(renderedPanel)>=0
    readonly property bool foldStyle: Orbit.appearance.shellLayout === "fold"
    readonly property string panelEdge: Orbit.appearance.panelPosition || "left"
    readonly property bool horizontalBar: panelEdge==="top" || panelEdge==="bottom"
    readonly property var taskbarRect: {var style=Orbit.appearance;return Orbit.panelSurfaceRect(panelEdge,Orbit.screenGeometry)}
    readonly property bool centeredPanel: Orbit.centeredPanels.indexOf(renderedPanel)>=0
    readonly property bool bottomSheet: foldStyle && Orbit.footerPanels.indexOf(renderedPanel)>=0
    readonly property int panelPadding: Theme.extraCompact ? 12 : Theme.compact ? 16 : 20
    readonly property int panelGap: Theme.extraCompact ? 6 : Theme.compact ? 10 : 14
    readonly property int panelOverhead: 2*panelPadding+panelGap+(foldStyle ? sheetHeader.implicitHeight : 30)
    readonly property bool foldPanel: foldStyle && (renderedPanel === "launcher" || renderedPanel === "overview")
    property int panelWidth: ({launcher:workspacePanelWidth,overview:workspacePanelWidth,ai:workspacePanelWidth,settings:420,"system-settings":600,capture:520,quick:350,music:350,usage:350,notifications:380,tray:310,bluetooth:380,battery:380,screenshot:380,"window-capture":500,switcher:620})[shell.renderedPanel] || 560
    readonly property bool panelRight: !foldStyle && Orbit.footerPanels.indexOf(renderedPanel)>=0
    readonly property int panelBodyWidth: Math.max(1,Math.min(sw-(foldStyle ? horizontalBar ? 32 : Theme.barThickness+28+(Orbit.appearance.taskbarFloating ? 16 : 0) : 24),panelWidth,760))
    readonly property int panelBodyHeight: Math.max(1,Math.min(sh-(foldStyle ? horizontalBar ? Theme.barThickness+28+(Orbit.appearance.taskbarFloating ? 16 : 0) : 32 : foldPanel ? (Theme.compact ? 144 : 172) : 100),panelHeight,620))
    onPanelBodyWidthChanged: queuePanelGeometry()
    onPanelBodyHeightChanged: queuePanelGeometry()
    property int panelHeight: {
        if(shell.workPanel) return Theme.compact ? 560 : 620;
        if(shell.renderedPanel === "window-capture") return 440;
        if(shell.renderedPanel === "screenshot") return Math.max(280,(pageLoader.item ? pageLoader.item.implicitHeight : 240)+shell.panelOverhead);
        if(shell.renderedPanel === "launcher") return Math.min(540,160+Math.max(2,Math.min(7,filteredApps().length))*(Theme.compact ? 50 : 60));
        if(shell.renderedPanel === "switcher") return Math.min(470,85+Math.max(1,Math.min(6,Orbit.switchWindows.length))*62);
        if(shell.renderedPanel === "overview") return Math.min(510,160+Math.max(1,Math.ceil(visibleWindows.length/3))*135);
        if(shell.renderedPanel === "settings") return Math.max(260,(pageLoader.item ? pageLoader.item.implicitHeight : 300)+shell.panelOverhead);
        if(shell.renderedPanel === "system-settings") return Math.max(320,(pageLoader.item ? pageLoader.item.implicitHeight : 400)+shell.panelOverhead);
        if(shell.renderedPanel === "session-exit") return Math.max(280,(pageLoader.item ? pageLoader.item.implicitHeight : 240)+shell.panelOverhead);
        if(shell.renderedPanel === "capture") return 350;
        if(shell.renderedPanel === "usage") return Math.max(280,(pageLoader.item ? pageLoader.item.implicitHeight : 240)+shell.panelOverhead);
        if(shell.renderedPanel === "music") return Math.max(240,(pageLoader.item ? pageLoader.item.implicitHeight : 180)+shell.panelOverhead);
        if(shell.renderedPanel === "quick") return Math.max(270,(pageLoader.item ? pageLoader.item.implicitHeight : 340)+shell.panelOverhead);
        if(shell.renderedPanel === "battery") return Power.state.batteryPresent || System.values.batteryPresent ? 360 : 280;
        if(shell.renderedPanel === "bluetooth") return Math.min(620,(pageLoader.item ? pageLoader.item.implicitHeight : 240)+shell.panelOverhead);
        if(shell.renderedPanel === "tray") return Math.min(440,100+Math.max(1,Tray.items.length+Background.items.length)*48+(Tray.legacyCount ? Math.ceil(Tray.legacyCount/8)*30+12 : 0));
        if(shell.renderedPanel === "notifications") return System.notifications.length ? 450 : 220;
        return 500;
    }
    function filteredApps() { return Orbit.launcherApps.filter(a => (!launchPinned || Orbit.appearance.pins.indexOf(a.id)>=0) && (a.name + " " + a.description).toLowerCase().includes(query.toLowerCase())); }
    function filteredWindows() { return Orbit.windows.filter(w => w.title.toLowerCase().includes(query.toLowerCase())); }
    function title() { return ({launcher:"Applications",overview:"Windows",ai:"Intelligence",settings:"Appearance","system-settings":"System settings",capture:"New note",quick:"Quick settings",music:"Music and sound",usage:"System usage",notifications:"Notifications",tray:"Background apps",bluetooth:"Bluetooth",battery:"Battery",screenshot:"Screenshot","window-capture":"Choose a window",switcher:"Switch windows"})[shell.renderedPanel] || "Abstract"; }
    property Timer clockTimer: Timer { interval: 60000; repeat: true; running: true; onTriggered: { shell.clockNow = new Date(); shell.hour = Qt.formatDateTime(new Date(), "hh:mm"); } }
    property Connections orbitConnections: Connections {
        target: Orbit
        function onPanelChanged() {
            shell.query="";shell.launchTab="Apps";
            enterPanel.stop();exitPanel.stop();swapPanel.stop();
            if(Orbit.panel === "")exitPanel.restart();
            else if(!shell.overlayShown) {shell.renderedPanel=Orbit.panel;shell.overlayShown=true;enterPanel.restart();}
            else if(shell.renderedPanel !== Orbit.panel)swapPanel.restart();
            else enterPanel.restart();
        }
    }
    function queuePanelGeometry() {if(overlayShown && renderedPanel!=="")panelGeometryTimer.restart();}
    onPanelWidthChanged: queuePanelGeometry()
    onPanelHeightChanged: queuePanelGeometry()
    property Timer panelGeometryTimer: Timer {
        interval: 0
        onTriggered: if(shell.overlayShown && shell.renderedPanel!=="")Orbit.syncPanelGeometry(shell.panelBodyWidth,shell.panelBodyHeight)
    }
    onRenderedPanelChanged: {Orbit.positionPanel(renderedPanel);queuePanelGeometry();}
    property SequentialAnimation enterPanel: SequentialAnimation {
        PropertyAction { target: surface;property: "opacity";value: 0 }
        PropertyAction { target: surfaceShift;property: "y";value: Theme.reducedMotion ? 0 : 7 }
        ParallelAnimation {
            NumberAnimation { target: surface;property: "opacity";to: 1;duration: Theme.motion;easing.type: Easing.OutCubic }
            NumberAnimation { target: surfaceShift;property: "y";to: 0;duration: Theme.motion;easing.type: Easing.OutCubic }
        }
    }
    property SequentialAnimation exitPanel: SequentialAnimation {
        NumberAnimation { target: surface;property: "opacity";to: 0;duration: Theme.reducedMotion ? 0 : Theme.economy ? 85 : 120;easing.type: Easing.InCubic }
        ScriptAction { script: {shell.overlayShown=false;shell.renderedPanel="";} }
    }
    property SequentialAnimation swapPanel: SequentialAnimation {
        NumberAnimation { target: surface;property: "opacity";to: 0;duration: Theme.reducedMotion ? 0 : Theme.economy ? 45 : 60 }
        ScriptAction { script: shell.renderedPanel=Orbit.panel }
        PauseAnimation { duration: Theme.reducedMotion ? 0 : 20 }
        NumberAnimation { target: surface;property: "opacity";to: 1;duration: Theme.reducedMotion ? 0 : Theme.economy ? 80 : 110;easing.type: Easing.OutCubic }
    }

    property Window desktopWindow: Window {
        id: desktopSurface; objectName: "desktopSurface"
        title: "Abstract — Desktop";property bool desktopIconsEnabled: Orbit.appearance.desktopIcons; property bool desktopEditing: false; visible: Orbit.surfacesReady; x: shell.sx; y: shell.sy; width: shell.sw; height: shell.sh
        flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint
        color: Theme.background
        DesktopBackground {anchors.fill: parent}
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; onDoubleClicked: Orbit.showPanel("launcher"); onClicked: mouse => { if(mouse.button === Qt.LeftButton){Orbit.dismiss();Orbit.closeContext();}else if(mouse.button === Qt.RightButton) {Orbit.openContext("desktop","",shell.sx+mouse.x,shell.sy+mouse.y);} } }

        DesktopIcons {
            anchors.fill: parent;anchors.leftMargin: shell.foldStyle && shell.panelEdge==="left" ? Theme.barThickness+16+(Orbit.appearance.taskbarFloating ? 16 : 0) : 16;anchors.rightMargin: shell.foldStyle && shell.panelEdge==="right" ? Theme.barThickness+16+(Orbit.appearance.taskbarFloating ? 16 : 0) : 16;anchors.topMargin: shell.foldStyle ? shell.panelEdge==="top" ? Theme.barThickness+16+(Orbit.appearance.taskbarFloating ? 16 : 0) : 16 : Theme.compact ? 44 : 52;anchors.bottomMargin: shell.foldStyle ? shell.panelEdge==="bottom" ? Theme.barThickness+16+(Orbit.appearance.taskbarFloating ? 16 : 0) : 16 : Theme.compact ? 76 : 90
            visible: Orbit.appearance.desktopIcons;controller: DesktopFiles;originX: shell.sx;originY: shell.sy;outputId: Orbit.selectedOutput
            onContextRequested: (path,x,y) => Orbit.openContext(path ? "desktop-file" : "desktop",path,x,y)
            onInteracted: {Orbit.dismiss();Orbit.closeContext();}
            onEditFocusRequested: (outputId,active) => Orbit.setDesktopEditing(outputId,active)
        }
    }

    property Window topbarWindow: Window {
        id: top; objectName: "topbarSurface"; title: "Abstract — Bar"
        visible: Orbit.surfacesReady; x: shell.foldStyle ? shell.taskbarRect.x : shell.sx; y: shell.foldStyle ? shell.taskbarRect.y : shell.sy; width: shell.foldStyle ? shell.taskbarRect.width : shell.sw; height: shell.foldStyle ? shell.taskbarRect.height : Orbit.isWayland ? 38 : (Theme.compact ? 30 : 38); color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        OrbitSpine {anchors.fill: parent;visible: shell.foldStyle;clockText: ClockFormat.shortTime(shell.clockNow,Orbit.appearance.clock24);clockNow: shell.clockNow;outputName: Orbit.selectedOutput}
        Item {
            visible: !shell.foldStyle
            width: parent.width;height: Theme.compact ? 30 : 38
            Rectangle { anchors.fill: parent;color: Theme.background }
        Row {
            id: topbarLeft;objectName: "topbarLeft"
            anchors.left: parent.left;anchors.leftMargin: 10;anchors.verticalCenter: parent.verticalCenter;spacing: 8
            OrbitButton { text: shell.foldStyle ? "◇  Abstract" : "◉  Abstract";quiet: true;implicitHeight: 28;hint: shell.foldStyle ? "Unfold Abstract · Super" : "Open Abstract · Super";onClicked: Orbit.showPanel("launcher") }
            Row {
                objectName: "workspaceIndicators";anchors.verticalCenter: parent.verticalCenter;spacing: 2
            Repeater { model: Orbit.desktops;OrbitButton { required property var modelData;text: String(modelData.id+1);quiet: true;implicitWidth: 20;implicitHeight: 20;padding: 2;
                background: Rectangle { radius: Theme.corner(6);color: parent.hovered ? Theme.hover : modelData.active ? Theme.raised : "transparent";border.width: modelData.active ? 1 : 0;border.color: Theme.border }
                hint: "Switch to workspace "+(modelData.id+1);onClicked: Orbit.switchDesktop(modelData.id) } }
            }
        }
        Text {
            objectName: "topbarClock";anchors.centerIn: parent;text: shell.clock;color: Theme.text;font.pixelSize: Theme.fontSize(11)
            height: 28;width: Math.min(implicitWidth,Math.max(80,parent.width-2*Math.max(topbarLeft.width,topbarRight.width)-24))
            horizontalAlignment: Text.AlignHCenter;verticalAlignment: Text.AlignVCenter;elide: Text.ElideRight
        }
        Row {
            id: topbarRight;objectName: "topbarRight"
            anchors.right: parent.right;anchors.rightMargin: 10;anchors.verticalCenter: parent.verticalCenter;spacing: 5
            ScreenshotButton {}
            OrbitButton { text: System.values.audioAvailable ? "♪ " + System.values.volume + "%" : "♪";quiet: true;implicitHeight: 28;hint: "Music and sound";onClicked: Orbit.showPanel("music") }
            OrbitButton { visible: Orbit.aiEnabled;text: "✧";quiet: true;implicitHeight: 28;hint: "AI";onClicked: Orbit.showPanel("ai") }
            Rectangle { width: 1;height: 12;anchors.verticalCenter: parent.verticalCenter;color: Theme.border }
            OrbitButton { text: "♧" + (System.notifications.length ? " " + System.notifications.length : "");quiet: true;implicitHeight: 28;hint: "Notifications";onClicked: Orbit.showPanel("notifications") }
            OrbitButton {
                text: Orbit.panel === "tray" ? "⌃" : "⌄";quiet: true;implicitWidth: 30;implicitHeight: 28
                visible: Tray.items.length+Background.items.length+Tray.legacyCount>0
                hint: "Background apps · " + (Tray.items.length+Background.items.length+Tray.legacyCount)
                onClicked: Orbit.showPanel("tray")
                contentItem: Canvas {
                    id: trayGlyph
                    property bool expanded: Orbit.panel === "tray"
                    onExpandedChanged: requestPaint()
                    implicitWidth: 14;implicitHeight: 14
                    onPaint: {var c=getContext("2d");c.clearRect(0,0,width,height);c.strokeStyle=Theme.text;c.lineWidth=1.5;c.lineCap="round";c.lineJoin="round";var x=Math.round(width/2);var y=Math.round(height/2);var direction=expanded ? 1 : -1;c.beginPath();c.moveTo(x-4,y+2*direction);c.lineTo(x,y-2*direction);c.lineTo(x+4,y+2*direction);c.stroke();}
                    Connections { target: Orbit;function onSettingsChanged(){trayGlyph.requestPaint();} }
                }
            }
            Rectangle { width: 1;height: 12;anchors.verticalCenter: parent.verticalCenter;color: Theme.border }
            OrbitButton { visible: Power.state.batteryPresent || System.values.batteryPresent;text: Power.state.percentageAvailable ? Power.state.batteryPercent+"%" : System.values.batteryPresent ? System.values.batteryPercent+"%" : "Battery";quiet: true;implicitHeight: 28;hint: "Battery and charging limit";onClicked: Orbit.showPanel("battery") }
            OrbitButton {
                objectName: "usageButton";quiet: true;implicitWidth: shell.sw>=900 ? Math.min(112,Math.max(48,Usage.username.length*6+28)) : 28;implicitHeight: 28
                hint: "System usage · Signed in as "+Usage.username;onClicked: Orbit.showPanel("usage")
                contentItem: Row {
                    spacing: 5
                    Canvas {
                        id: usageGlyph;width: 13;height: 14;anchors.verticalCenter: parent.verticalCenter
                        onPaint: {var c=getContext("2d");c.clearRect(0,0,width,height);c.fillStyle=Theme.text;c.fillRect(1,8,3,5);c.fillRect(5,3,3,10);c.fillRect(9,6,3,7);}
                        Connections { target: Orbit;function onSettingsChanged(){usageGlyph.requestPaint();} }
                    }
                    Text { visible: shell.sw>=900;text: Usage.username;width: Math.min(80,implicitWidth);elide: Text.ElideRight;color: Theme.text;font.pixelSize: Theme.fontSize(11);height: 16;verticalAlignment: Text.AlignVCenter;textFormat: Text.PlainText }
                }
            }
            OrbitButton { text: "☷";quiet: true;implicitHeight: 28;hint: "Quick settings";onClicked: Orbit.showPanel("quick") }
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
        }
    }

    property Window dockReserveWindow: Window {
        objectName: "dockReserveSurface";title: "Abstract — Dock reserve"
        visible: Orbit.isWayland && Orbit.surfacesReady && !shell.foldStyle;width: 1;height: 1;color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
    }

    property Window dockWindow: Window {
        id: dock;objectName: "dockSurface";title: "Abstract — Dock"
        visible: Orbit.surfacesReady && !shell.foldStyle
        width: Orbit.isWayland ? Orbit.dockGeometry.surfaceWidth : Orbit.dockGeometry.bodyWidth
        height: Orbit.isWayland ? Orbit.dockGeometry.surfaceHeight : Orbit.dockGeometry.bodyHeight
        x: shell.sx+(Orbit.appearance.dockAlign==="left" ? 12 : Orbit.appearance.dockAlign==="right" ? shell.sw-width-12 : (shell.sw-width)/2)
        y: shell.sy+shell.sh-height-10;color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        onVisibleChanged: if(visible)dockBody.updateMask()
        Rectangle {
            id: dockBody;objectName: "dockBody"
            width: Orbit.dockGeometry.bodyWidth;height: Orbit.dockGeometry.bodyHeight
            y: parent.height-height
            x: !Orbit.isWayland || Orbit.appearance.dockAlign==="left" ? 0 : Orbit.appearance.dockAlign==="right" ? parent.width-width : Math.round((parent.width-width)/2)
            readonly property real logicalLeft: shell.sx+(Orbit.appearance.dockAlign==="left" ? 12 : Orbit.appearance.dockAlign==="right" ? shell.sw-12-width : (shell.sw-width)/2)
            readonly property real logicalTop: shell.sy+shell.sh-height-10
            radius: Theme.corner(shell.foldStyle ? 6 : 14);color: Theme.surface;border.color: Theme.border
            function screenPoint(item,px,py) {
                var local=item.mapToItem(dockBody,px,py);
                return {x:Math.round(logicalLeft+local.x),y:Math.round(logicalTop+local.y)};
            }
            function updateMask(){Orbit.updateDockMask(Math.floor(x),Math.floor(y),Math.ceil(width),Math.ceil(height));}
            onXChanged: updateMask()
            onYChanged: updateMask()
            onWidthChanged: updateMask()
            onHeightChanged: updateMask()
            Row {
                id: dockRow;x: Orbit.dockGeometry.padding;anchors.verticalCenter: parent.verticalCenter;spacing: Orbit.dockGeometry.gap
                DockToolButton { kind: shell.foldStyle ? "fold" : "apps";width: Orbit.dockGeometry.slot;height: Theme.compact ? 38 : 50;hint: "";Accessible.name: shell.foldStyle ? "Unfold Abstract" : "Applications";onClicked: Orbit.showPanel("launcher") }
                Repeater {
                    model: Orbit.dockApps.slice(0,shell.dockCapacity)
                    Item {
                        id: appItem
                        required property var modelData;width: Orbit.dockGeometry.slot;height: Theme.compact ? 38 : 50
                        Rectangle { anchors.fill: parent;radius: Theme.corner(shell.foldStyle ? 4 : 10);color: dockHit.containsMouse ? Theme.hover : modelData.windows.some(w => w.active) ? Theme.raised : "transparent" }
                        Image {
                            id: dockAppIcon
                            x: shell.foldStyle ? 8 : (parent.width-width)/2;y: (parent.height-height)/2
                            source: "image://icons/"+modelData.icon;width: shell.foldStyle ? 22 : Theme.compact ? 28 : 36;height: width
                            sourceSize: shell.foldStyle ? Qt.size(24,24) : Qt.size(40,40)
                        }
                        Text {
                            visible: shell.foldStyle && Orbit.dockGeometry.slot>=64
                            x: dockAppIcon.x+dockAppIcon.width+6;y: 0;width: Math.max(0,parent.width-x-7);height: parent.height
                            text: modelData.name;elide: Text.ElideRight;verticalAlignment: Text.AlignVCenter;textFormat: Text.PlainText
                            color: modelData.windows.length ? Theme.text : Theme.muted;font.pixelSize: Theme.fontSize(10)
                        }
                        Rectangle {
                            x: shell.foldStyle ? 6 : (parent.width-width)/2;y: shell.foldStyle ? 1 : parent.height-height
                            width: shell.foldStyle ? parent.width-12 : modelData.windows.length>1 ? 12 : 4;height: shell.foldStyle ? 2 : 3
                            radius: shell.foldStyle ? 0 : 2;color: Theme.accent
                            visible: shell.foldStyle ? modelData.windows.some(w => w.active) : modelData.windows.length>0
                        }
                        MouseArea {
                            id: dockHit;anchors.fill: parent;hoverEnabled: true;acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: mouse => {if(mouse.button===Qt.RightButton){var p=dockBody.screenPoint(dockHit,width/2,0);Orbit.openDockContext(modelData.id,p.x,p.y);}else Orbit.activateDock(modelData.id,false);}
                            onEntered: {Orbit.queueItemTooltip(dockHit,modelData.name+(modelData.windows.length>1 ? " · "+modelData.windows.length+" windows" : ""),width/2,0);}
                            onExited: Orbit.hideTooltip()
                        }
                        Accessible.name: modelData.name;Accessible.role: Accessible.Button;Accessible.onPressAction: Orbit.activateDock(modelData.id,false)
                    }
                }
                Item {
                    id: dockOverflow;visible: Orbit.dockGeometry.overflowCount>0;width: Orbit.dockGeometry.slot;height: Theme.compact ? 38 : 50
                    Rectangle { anchors.fill: parent;radius: Theme.corner(10);color: overflowHit.containsMouse ? Theme.hover : "transparent" }
                    Text { anchors.centerIn: parent;text: Orbit.dockGeometry.overflowCount>99 ? "99+" : "+"+Orbit.dockGeometry.overflowCount;color: Theme.text;font.pixelSize: Theme.fontSize(12) }
                    MouseArea {
                        id: overflowHit;anchors.fill: parent;hoverEnabled: true;onClicked: Orbit.showPanel("overview")
                        onEntered: {Orbit.queueItemTooltip(dockOverflow,"All open windows",width/2,0);}
                        onExited: Orbit.hideTooltip()
                    }
                    Accessible.name: "All open windows";Accessible.role: Accessible.Button;Accessible.onPressAction: Orbit.showPanel("overview")
                }
            }
        }
    }

    property Window overlayWindow: Window {
        id: overlay; property bool heldFocus: false
        readonly property bool utilityPanel: shell.renderedPanel !== "switcher"
        onActiveChanged: {
            if(active){heldFocus=true;Orbit.settlePanelFocus();}
            else if(heldFocus && visible && utilityPanel && Orbit.panel!=="" && !swapPanel.running && !enterPanel.running) {heldFocus=false;Orbit.utilityFocusLost();}
        }
        objectName: "overlaySurface"; title: "Abstract — Action surface"
        visible: Orbit.surfacesReady && shell.overlayShown
        width: Orbit.isWayland ? 760 : shell.panelBodyWidth;height: Orbit.isWayland ? 620 : shell.panelBodyHeight
        readonly property var popupOrigin: {var style=Orbit.appearance;var tasks=Orbit.dockApps;return Orbit.panelPopupOrigin(shell.renderedPanel,width,height,Orbit.screenGeometry,shell.panelEdge)}
        x: popupOrigin.x
        y: popupOrigin.y
        color: "transparent";flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        onVisibleChanged: {
            if(visible) {if(!Orbit.isWayland)requestActivate();overlayItem.forceActiveFocus();shell.queuePanelGeometry();}
            else heldFocus=false;
        }
        Item {
            id: overlayItem; anchors.fill: parent; focus: true
            Keys.onEscapePressed: {if(Orbit.switchActive)Orbit.cancelSwitch();else Orbit.dismiss();}
            Keys.onPressed: event => {
                if(!Orbit.switchActive)return;
                if(event.key===Qt.Key_Tab || event.key===Qt.Key_Right || event.key===Qt.Key_Down) {Orbit.cycleSwitch((event.modifiers & Qt.ShiftModifier) ? -1 : 1);event.accepted=true;}
                else if(event.key===Qt.Key_Left || event.key===Qt.Key_Up) {Orbit.cycleSwitch(-1);event.accepted=true;}
                else if(event.key===Qt.Key_Return || event.key===Qt.Key_Enter) {Orbit.acceptSwitch();event.accepted=true;}
            }
            Keys.onReleased: event => {if(Orbit.switchActive && event.key===Qt.Key_Alt) {Orbit.acceptSwitch();event.accepted=true;}}
            MouseArea { anchors.fill: parent; onClicked: Orbit.dismiss() }
            Rectangle {
                id: surface
                objectName: "panelBody"
                width: shell.panelBodyWidth;height: shell.panelBodyHeight
                readonly property var bodyMask: Orbit.panelBodyMask(shell.renderedPanel,parent.width,parent.height,width,height,shell.panelEdge)
                x: Orbit.isWayland ? bodyMask.x : 0
                y: Orbit.isWayland ? bodyMask.y : 0
                radius: shell.foldStyle ? Theme.corner(6) : Theme.radius; color: shell.foldStyle ? "transparent" : Theme.background; border.color: Theme.border; border.width: shell.foldStyle ? 0 : 1
                SheetChrome {anchors.fill: parent;visible: shell.foldStyle}
                transform: Translate { id: surfaceShift }
                enabled: !swapPanel.running
                MouseArea { anchors.fill: parent; onClicked: mouse => mouse.accepted=true }
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: shell.panelPadding; spacing: shell.panelGap
                    SheetHeader {id: sheetHeader;visible: shell.foldStyle && !shell.foldPanel;Layout.fillWidth: true;Layout.preferredHeight: implicitHeight;compact: true;section: "ABSTRACT / "+(shell.renderedPanel==="notifications" ? "INBOX" : shell.renderedPanel==="screenshot" ? "CAPTURE" : "CONTROLS");title: shell.title();onCloseRequested: Orbit.closePanel()}
                    RowLayout {
                        visible: !shell.foldPanel && !shell.foldStyle
                        Layout.fillWidth: true;Layout.preferredHeight: 30
                        Rectangle {visible: shell.foldStyle;Layout.leftMargin: 2;Layout.rightMargin: 6;width: 11;height: 11;rotation: 45;color: "transparent";border.color: Theme.accent;Rectangle{x: 3;y: 3;width: 5;height: 5;color:"transparent";border.color:Theme.accent}}
                        ColumnLayout {
                            Layout.fillWidth: true;spacing: 1
                            Text {visible: shell.foldStyle;text: "ABSTRACT / "+(shell.renderedPanel==="notifications" ? "INBOX" : shell.renderedPanel.indexOf("capture")>=0 || shell.renderedPanel==="screenshot" ? "CAPTURE" : "SYSTEM");color: Theme.accent;font.pixelSize: Theme.fontSize(9);font.letterSpacing: 1}
                            Text {text: shell.workPanel && !shell.foldStyle ? "Abstract" : shell.title();color: Theme.text;font.pixelSize: Theme.fontSize(shell.foldStyle ? 14 : 17);font.weight: Font.Medium;Layout.fillWidth: true;elide: Text.ElideRight}
                        }
                        Text {visible: shell.workPanel && !shell.foldStyle;text: "YOUR WORKSPACE";color: Theme.faint;font.pixelSize: Theme.fontSize(9);font.letterSpacing: 1.2}
                        IconButton {objectName: "foldPanelCloseButton";iconName: "close";quiet: true;implicitWidth: 28;implicitHeight: 28;hint: "Close panel";onClicked: Orbit.closePanel()}
                    }
                    WorkspaceNavigation {
                        visible: shell.workPanel && !shell.foldPanel && !shell.foldStyle;Layout.fillWidth: true
                        current: shell.renderedPanel;aiEnabled: Orbit.aiEnabled
                        counts: ({launcher:Orbit.apps.length,overview:Orbit.windows.length})
                        onSelected: view => Orbit.showPanel(view)
                    }
                    Loader {
                        id: pageLoader; Layout.fillWidth: true; Layout.fillHeight: true
                        active: shell.renderedPanel !== ""
                        sourceComponent: shell.foldPanel ? foldPage : ({launcher:launcherPage,overview:overviewPage,ai:aiPage,capture:capturePage,settings:settingsPage,"system-settings":systemSettingsPage,"session-exit":sessionExitPage,quick:quickPage,music:musicPage,usage:usagePage,notifications:notificationsPage,tray:trayPage,bluetooth:bluetoothPage,battery:batteryPage,screenshot:screenshotPage,"window-capture":windowCapturePage,switcher:switcherPage})[shell.renderedPanel] || null
                    }

                }
            }

            Rectangle {
                id: panelTooltip;objectName: "panelTooltip";z: 1000
                visible: Orbit.tooltip.inline === true && Orbit.tooltip.text !== undefined
                x: Orbit.tooltip.localX || 0;y: Orbit.tooltip.localY || 0
                width: Orbit.tooltip.width || 160;height: 34
                radius: Theme.corner(7);color: Theme.surface;border.color: Theme.border
                onVisibleChanged: if(visible){opacity=0;panelTipEnter.restart();}
                Text { anchors.centerIn: parent;width: parent.width-18;text: Orbit.tooltip.text || "";font.pixelSize: Theme.fontSize(11);color: Theme.text;elide: Text.ElideRight;horizontalAlignment: Text.AlignHCenter;textFormat: Text.PlainText }
                NumberAnimation { id: panelTipEnter;target: panelTooltip;property: "opacity";to: 1;duration: Theme.motion }
            }
        }
    }

    property Window screenshotSelectionWindow: Window {
        id: screenshotSelection;objectName: "screenshotSelectionSurface";title: "Abstract — Screenshot selection"
        visible: Orbit.surfacesReady && Screenshots.state.selecting
        x: shell.sx;y: shell.sy;width: shell.sw;height: shell.sh;color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        onVisibleChanged: if(visible){if(!Orbit.isWayland)requestActivate();screenshotSelectionItem.forceActiveFocus();}
        ScreenshotSelection { id: screenshotSelectionItem;anchors.fill: parent }
    }

    property Window noticeWindow: Window {
        id: notification; objectName: "noticeSurface";title: "Abstract — Notice"; visible: Orbit.surfacesReady && (Orbit.notice !== "" || System.currentNotification.summary !== undefined); color: "transparent"
        x: shell.sx + (shell.sw-width)/2; y: shell.sy+shell.sh-153; width: Math.min(shell.sw-28,380); height: 64
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        Rectangle { anchors.fill: parent; radius: Theme.corner(10); color: Theme.surface; border.color: Theme.border
            Text { anchors.centerIn: parent; width: parent.width-30; text: Orbit.notice || ((System.currentNotification.summary || "")+"\n"+(System.currentNotification.body || "")); color: Theme.text; font.pixelSize: Theme.fontSize(12); horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; textFormat: Text.PlainText }
            MouseArea { anchors.fill: parent;enabled: Orbit.notice==="" && System.currentNotification.id!==undefined;cursorShape: Qt.PointingHandCursor;onClicked: {Orbit.dismiss();System.activateNotification(System.currentNotification.id);} }
        }
        Timer { interval: 4500; running: notification.visible; onTriggered: {Orbit.clearNotice();System.hideNotification();} }
    }

    property Window tooltipSurface: Window {
        objectName: "tooltipSurface";title: "Abstract — Tooltip";visible: Orbit.surfacesReady && Orbit.tooltip.text !== undefined
        x: Orbit.tooltip.x || 0;y: Orbit.tooltip.y || 36;width: Orbit.isWayland ? 300 : (Orbit.tooltip.width || 160);height: 34;color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
        onVisibleChanged: if(visible){tipBody.opacity=0;tipEnter.restart();}
        NumberAnimation { id: tipEnter;target: tipBody;property: "opacity";to: 1;duration: Theme.motion }
        Rectangle { id: tipBody;width: Orbit.tooltip.width || 160;height: parent.height;radius: Theme.corner(7);color: Theme.surface;border.color: Theme.border
            Text { anchors.centerIn: parent;width: parent.width-18;text: Orbit.tooltip.text || "";font.pixelSize: Theme.fontSize(11);color: Theme.text;elide: Text.ElideRight;horizontalAlignment: Text.AlignHCenter;textFormat: Text.PlainText }
        }
    }
    property Window contextSurface: Window {
        id: contextWindow;objectName: "contextSurface";title: "Abstract — Menu";visible: Orbit.surfacesReady && (Orbit.context.items !== undefined || (Orbit.isWayland && Orbit.panel !== ""))
        x: shell.sx;y: shell.sy;width: shell.sw;height: shell.sh;color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        onVisibleChanged: {Orbit.syncContextSurface();if(visible && Orbit.context.items!==undefined && !Orbit.isWayland)requestActivate();}
        property Connections contextState: Connections { target: Orbit;function onInteractionChanged(){Orbit.syncContextSurface();}function onPanelChanged(){Orbit.syncContextSurface();} }
        NumberAnimation { id: contextEnter;target: contextPopup;property: "opacity";to: 1;duration: Theme.motion;easing.type: Easing.OutCubic }
        Item {
            id: contextRoot;anchors.fill: parent;focus: true
            Keys.onEscapePressed: {if(Orbit.context.items!==undefined)Orbit.closeContext();else Orbit.dismiss();}
            Keys.onDownPressed: contextList.currentIndex=(contextList.currentIndex+1)%contextList.count
            Keys.onUpPressed: contextList.currentIndex=(contextList.currentIndex+contextList.count-1)%contextList.count
            Keys.onReturnPressed: Orbit.contextAction(contextList.currentIndex)
            MouseArea { anchors.fill: parent;acceptedButtons: Qt.LeftButton | Qt.RightButton;onClicked: {if(Orbit.context.items!==undefined)Orbit.closeContext();else Orbit.dismiss();} }
            Rectangle {
                id: contextPopup;objectName: "contextPopup";visible: Orbit.context.items !== undefined
                onVisibleChanged: if(visible){Orbit.syncContextSurface();contextRoot.forceActiveFocus();contextList.currentIndex=0;opacity=0;contextEnter.restart();}
                width: 250;height: contextList.contentHeight+12;radius: Theme.corner(10);color: Theme.surface;border.color: Theme.border
                x: Math.max(8,Math.min((Orbit.context.x || 0)-shell.sx-(Orbit.context.placement === "above" ? width/2 : 0),parent.width-width-8));y: Math.max(36,Math.min((Orbit.context.y || 0)-shell.sy-(Orbit.context.placement === "above" ? height+8 : 0),parent.height-height-12))
                ListView {
                    id: contextList;anchors.fill: parent;anchors.margins: 6;interactive: false;model: Orbit.context.items || []
                    delegate: Rectangle {
                        required property var modelData;required property int index;width: ListView.view.width;height: 32;radius: Theme.corner(6);color: index===contextList.currentIndex ? Theme.hover : "transparent"
                        Text { anchors.fill: parent;anchors.leftMargin: 9;anchors.rightMargin: 9;verticalAlignment: Text.AlignVCenter;text: modelData.label;color: modelData.enabled === false ? Theme.faint : Theme.text;font.pixelSize: Theme.fontSize(12);elide: Text.ElideRight;textFormat: Text.PlainText }
                        MouseArea { enabled: modelData.enabled !== false;anchors.fill: parent;hoverEnabled: true;onEntered: contextList.currentIndex=index;onClicked: Orbit.contextAction(index) }
                    }
                }
            }

        }
    }

    property Component launcherComponent: Component {id:launcherPage;FoldWorkspace {}}

    property Component foldComponent: Component { id: foldPage;FoldWorkspace {} }
    property Component overviewComponent: Component { id: overviewPage;WindowOverview { windows: shell.visibleWindows } }

    property Component captureComponent: Component {
        id: capturePage
        ColumnLayout {
            spacing: 18
            OrbitField { id: noteTitle; Layout.fillWidth: true; placeholderText: "Give this thought a name"; Component.onCompleted: forceActiveFocus() }
            TextArea {
                id: noteBody; Layout.fillWidth: true; Layout.fillHeight: true; placeholderText: "A thought, a text selection, a link…"; color: Theme.text; placeholderTextColor: Theme.muted; wrapMode: TextEdit.Wrap; selectByMouse: true; padding: 18
                background: Rectangle { color: Theme.surface; radius: Theme.corner(13); border.color: Theme.border }
            }
            RowLayout {
                Text { text: "Stored locally in " + Orbit.workspace; color: Theme.muted; font.pixelSize: Theme.fontSize(11) }
                Item { Layout.fillWidth: true }
                OrbitButton { text: "Capture →"; accent: true; onClicked: Orbit.capture(noteTitle.text,noteBody.text) }
            }
        }
    }

    property Component aiComponent: Component { id: aiPage;IntelligencePanel {} }

    property Component switcherComponent: Component { id: switcherPage;WindowSwitcher {} }
    property Component settingsComponent: Component { id: settingsPage;AppearancePanel {} }
    property Component sessionExitComponent: Component {id:sessionExitPage;SessionExitPanel {}}
    property Component systemSettingsComponent: Component { id: systemSettingsPage;SystemPanel {} }
    property Component usageComponent: Component { id: usagePage;UsagePanel {} }
    property Component musicComponent: Component { id: musicPage;MusicPanel {compactControls: true} }
    property Component quickComponent: Component { id: quickPage;QuickPanel {} }
    property Component windowCaptureComponent: Component {
        id: windowCapturePage
        WindowCapturePicker {
            windows: Orbit.windows.filter(w => !w.minimized && Orbit.desktops.some(d => d.active && d.id===w.desktop))
            onSelected: ident => Screenshots.captureSelectedWindow(ident)
            onCanceled: Orbit.showPanel("screenshot")
        }
    }
    property Component screenshotComponent: Component { id: screenshotPage;ScreenshotPanel {} }
    property Component batteryComponent: Component { id: batteryPage;BatteryPanel {} }
    property Component bluetoothComponent: Component { id: bluetoothPage;BluetoothPanel {} }
    property Component trayComponent: Component { id: trayPage;TrayPanel {} }
    property Component notificationsComponent: Component { id: notificationsPage;NotificationsPanel {} }
}
