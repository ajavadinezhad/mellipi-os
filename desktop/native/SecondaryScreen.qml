import QtQuick 2.15
import QtQuick.Window 2.15
import "."
import "ClockFormat.js" as ClockFormat
QtObject {
    id: output
    property string screenName: ""
    property var geometry: ({x:0,y:0,width:800,height:600})
    property bool ready: false
    property string panelEdge: Orbit.appearance.panelPosition || "left"
    property var barGeometry: {var style=Orbit.appearance;return Orbit.panelSurfaceRect(panelEdge,geometry)}
    property date now: new Date()
    property string clock: Qt.formatDateTime(now,(Orbit.appearance.clockDate ? "ddd, MMM d · " : "")+(Orbit.appearance.clock24 ? "HH:mm" : "h:mm AP"))
    property string shortClock: ClockFormat.shortTime(now,Orbit.appearance.clock24)
    property var dock: Orbit.dockForWidth(geometry.width)
    property Connections changes: Connections {target: Orbit;function onDockLayoutChanged(){output.dock=Orbit.dockForWidth(output.geometry.width);}}
    onGeometryChanged: dock=Orbit.dockForWidth(geometry.width)
    property Timer clockTimer: Timer {interval: 60000;repeat: true;running: output.ready;onTriggered: output.now=new Date()}
    property Window desktop: Window {
        objectName: "secondaryDesktopSurface";title: "Mellipi — Desktop"
        property string orbitOutputName: output.screenName
        property bool desktopIconsEnabled: Orbit.appearance.desktopIcons
        property bool desktopEditing: false
        x: output.geometry.x;y: output.geometry.y;width: output.geometry.width;height: output.geometry.height
        visible: output.ready && Orbit.surfacesReady;color: Theme.background
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint
        DesktopBackground {anchors.fill: parent}
        MouseArea {anchors.fill: parent;acceptedButtons: Qt.LeftButton | Qt.RightButton;onClicked: mouse => {if(mouse.button===Qt.RightButton){Orbit.openContextOn("desktop","",output.geometry.x+mouse.x,output.geometry.y+mouse.y,output.screenName);}else Orbit.dismiss();}onDoubleClicked: Orbit.showPanelOn("launcher",output.screenName)}
        DesktopIcons {
            anchors.fill: parent;anchors.leftMargin: output.panelEdge==="left" ? Theme.barThickness+16+(Orbit.appearance.taskbarFloating ? 16 : 0) : 16;anchors.rightMargin: output.panelEdge==="right" ? Theme.barThickness+16+(Orbit.appearance.taskbarFloating ? 16 : 0) : 16;anchors.topMargin: output.panelEdge==="top" ? Theme.barThickness+16+(Orbit.appearance.taskbarFloating ? 16 : 0) : 16;anchors.bottomMargin: output.panelEdge==="bottom" ? Theme.barThickness+16+(Orbit.appearance.taskbarFloating ? 16 : 0) : 16
            visible: Orbit.appearance.desktopIcons;controller: DesktopFiles;originX: output.geometry.x;originY: output.geometry.y;outputId: output.screenName
            onContextRequested: (path,x,y) => Orbit.openContextOn(path ? "desktop-file" : "desktop",path,x,y,output.screenName)
            onInteracted: {Orbit.dismiss();Orbit.closeContext();}
            onEditFocusRequested: (outputId,active) => Orbit.setDesktopEditing(outputId,active)
        }

    }
    property Window topbar: Window {
        id: secondaryBar
        objectName: "secondaryTopbarSurface";title: "Mellipi — Top panel"
        property string orbitOutputName: output.screenName
        x: output.barGeometry.x;y: output.barGeometry.y;width: output.barGeometry.width;height: output.barGeometry.height
        visible: output.ready && Orbit.surfacesReady;color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        property rect orbitTaskbarBody: spine.visible ? spine.bodyGeometry : Qt.rect(0,0,0,0)
        function syncBarMask() {Orbit.syncTaskbarMask(secondaryBar);}
        onOrbitTaskbarBodyChanged: Qt.callLater(syncBarMask)
        OrbitSpine {id: spine;anchors.fill: parent;visible: Theme.fold;clockText: output.shortClock;clockNow: output.now;outputName: output.screenName}
        FoldTopbar {visible: !Theme.fold;width: parent.width;height: Theme.compact ? 30 : 38;clockText: output.clock;screenWidth: output.geometry.width;outputName: output.screenName}
    }
    property Window reserve: Window {
        objectName: "secondaryDockReserveSurface";title: "Mellipi — Dock reserve"
        property string orbitOutputName: output.screenName
        x: output.geometry.x+output.geometry.width/2;y: output.geometry.y+output.geometry.height-1;width: 1;height: 1
        visible: output.ready && Orbit.surfacesReady && !Theme.fold;color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
    }
    property Window dockWindow: Window {
        id: edge;objectName: "secondaryDockSurface";title: "Mellipi — Dock"
        property string orbitOutputName: output.screenName
        x: output.geometry.x+(Orbit.appearance.dockAlign==="left" ? 12 : Orbit.appearance.dockAlign==="right" ? output.geometry.width-width-12 : (output.geometry.width-width)/2)
        y: output.geometry.y+output.geometry.height-height-10;width: output.dock.surfaceWidth;height: output.dock.surfaceHeight
        visible: output.ready && Orbit.surfacesReady && !Theme.fold;color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        Rectangle {
            id: body;objectName: "secondaryDockBody"
            width: output.dock.bodyWidth;height: output.dock.bodyHeight;y: parent.height-height
            x: Orbit.appearance.dockAlign==="left" ? 0 : Orbit.appearance.dockAlign==="right" ? parent.width-width : Math.round((parent.width-width)/2)
            color: Theme.surface;border.color: Theme.border;border.width: Theme.surfaceOutline;radius: Theme.corner(6)
            onXChanged: Orbit.maskSecondaryDock(edge,Math.floor(x),Math.floor(y),Math.ceil(width),Math.ceil(height))
            onYChanged: Orbit.maskSecondaryDock(edge,Math.floor(x),Math.floor(y),Math.ceil(width),Math.ceil(height))
            onWidthChanged: Orbit.maskSecondaryDock(edge,Math.floor(x),Math.floor(y),Math.ceil(width),Math.ceil(height))
            onHeightChanged: Orbit.maskSecondaryDock(edge,Math.floor(x),Math.floor(y),Math.ceil(width),Math.ceil(height))
            Row {
                x: output.dock.padding;anchors.verticalCenter: body.verticalCenter;spacing: output.dock.gap
                DockToolButton {kind: Theme.fold ? "fold" : "apps";width: output.dock.slot;height: Theme.compact ? 38 : 50;Accessible.name: "Open Mellipi";onClicked: Orbit.showPanelOn("launcher",output.screenName)}
                Repeater {
                    model: Orbit.dockApps.slice(0,output.dock.capacity)
                    OrbitButton {
                        id: task;required property var modelData
                        width: output.dock.slot;implicitWidth: output.dock.slot;height: Theme.compact ? 38 : 50;padding: 5;quiet: true
                        Accessible.name: modelData.name;hint: modelData.name
                        contentItem: Item {
                            Image {id: icon;width: 22;height: 22;anchors.verticalCenter: parent.verticalCenter;x: Theme.fold ? 2 : (parent.width-width)/2;source: Theme.iconSource(task.modelData.icon);sourceSize: Qt.size(32,32)}
                            Text {visible: Theme.fold;anchors.left: icon.right;anchors.leftMargin: 6;anchors.right: parent.right;anchors.verticalCenter: parent.verticalCenter;text: task.modelData.name;font.pixelSize: Theme.fontSize(10);color: Theme.text;elide: Text.ElideRight;textFormat: Text.PlainText}
                            Rectangle {anchors.horizontalCenter: parent.horizontalCenter;anchors.bottom: parent.bottom;width: 4;height: 2;color: Theme.accent;visible: task.modelData.windows.length>0}
                        }
                        onClicked: Orbit.activateDock(modelData.id,false)
                        MouseArea {anchors.fill: parent;acceptedButtons: Qt.RightButton;onClicked: mouse => {var p=Orbit.itemScreenPoint(task,mouse.x,mouse.y);Orbit.openDockContext(task.modelData.id,p.x,p.y);}}
                    }
                }
                DockToolButton {visible: output.dock.overflowCount>0;kind: "windows";width: output.dock.slot;height: Theme.compact ? 38 : 50;Accessible.name: "All windows";onClicked: Orbit.showPanelOn("overview",output.screenName)}
            }
        }
    }
}
