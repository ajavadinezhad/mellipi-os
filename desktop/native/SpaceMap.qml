import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

FocusScope {
    id: map
    objectName: "spaceMap"
    property var spaces: []
    property int selectedId: -1
    property int page: 0
    property string checkpointId: ""
    property string moveWindowId: ""
    readonly property var selected: spaces.find(space => space.id===selectedId) || ({windows:[],id:-1,count:0})
    readonly property var checkpoint: {
        const revision=Arrangements.checkpoints;
        const topology=map.spaces;
        return map.checkpointId ? Arrangements.checkpointPreview(map.checkpointId) : ({});
    }
    function refresh() {
        const latest=Orbit.spaceMapSnapshot();
        if(!latest.some(space => space.id===selectedId)) {
            const active=latest.find(space => space.active) || latest[0];
            selectedId=active ? active.id : -1;
        }
        spaces=latest;
    }
    function focusTile(index) {
        const tile=spaceTiles.itemAt(index);
        if(tile){selectedId=tile.space.id;moveWindowId="";tile.forceActiveFocus(Qt.TabFocusReason);}
    }
    function focusSelected() {
        if(page===0)focusTile(Math.max(0,spaces.findIndex(space => space.id===selectedId)));
    }
    function finishMove(ident,space) {
        Orbit.moveWindow(ident,space+1);
        moveWindowId="";
        Qt.callLater(focusSelected);
    }
    function focusCheckpointBack() {
        if(checkpointId)checkpointBack.forceActiveFocus(Qt.TabFocusReason);
    }
    function openCheckpoint(ident) {
        checkpointId=ident;
        Qt.callLater(focusCheckpointBack);
    }
    function showPage(index) {
        if(page===index)return;
        page=index;
        checkpointId="";
        moveWindowId="";
        if(viewport.contentItem && viewport.contentItem.contentY!==undefined)
            viewport.contentItem.contentY=0;
        if(index===0)Qt.callLater(focusSelected);
    }
    Component.onCompleted: {
        refresh();
        Qt.callLater(focusSelected);
    }
    Connections {
        target: Orbit
        function onWindowsChanged(){map.refresh();}
        function onGeometryChanged(){map.refresh();}
    }

    component Schematic: Rectangle {
        id: diagram
        property var tiles: []
        radius:Theme.corner(5);color:Theme.background;clip:true
        Repeater {
            model: diagram.tiles
            delegate: Rectangle {
                required property var modelData
                x:modelData.tile.x*diagram.width;y:modelData.tile.y*diagram.height
                width:Math.max(2,modelData.tile.w*diagram.width-1)
                height:Math.max(2,modelData.tile.h*diagram.height-1)
                opacity:modelData.available===false ? .43 : 1
                color:Theme.selectedSurface;radius:Theme.corner(3)
                border.width:1;border.color:Theme.controlBorder
                Image {
                    anchors.centerIn:parent;width:16;height:16
                    visible:parent.width>=20 && parent.height>=20 && modelData.available!==false
                    source:visible ? Theme.iconSource(modelData.icon) : ""
                    sourceSize:Qt.size(24,24);fillMode:Image.PreserveAspectFit
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent;spacing: Theme.rowGap
        GridLayout {
            Layout.fillWidth: true
            columns: width >= Theme.fontSize(320) ? 3 : 1
            columnSpacing: Theme.rowGap;rowSpacing: 4
            OrbitButton {Layout.fillWidth:true;Layout.preferredWidth:1;text:"Spaces";accent:map.page===0;onClicked:map.showPage(0)}
            OrbitButton {Layout.fillWidth:true;Layout.preferredWidth:1;objectName:"spaceMapCheckpoints";text:"Checkpoints";accent:map.page===1;onClicked:map.showPage(1)}
            OrbitButton {Layout.fillWidth:true;Layout.preferredWidth:1;objectName:"spaceMapSavedLayouts";text:"Saved layouts";accent:map.page===2;onClicked:map.showPage(2)}
        }
        Loader {
            active: map.page===2;visible: active
            Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:0
            sourceComponent: Component {LayoutsPanel {}}
        }
        ScrollView {
            id: viewport
            visible: map.page!==2
            Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 0
            clip: true;contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: viewport.availableWidth-4;spacing: Theme.rowGap
                GridLayout {
                    id: grid
                    visible: map.page===0
                    Layout.fillWidth: true
                    columns: width >= Theme.fontSize(490) ? 4 : 2
                    columnSpacing: Theme.rowGap;rowSpacing: Theme.rowGap
                    Repeater {
                        id: spaceTiles
                        model: map.page===0 ? map.spaces.length : 0
                        delegate: OrbitButton {
                            id: card
                            required property int index
                            readonly property var space: map.spaces[index] || ({id:-1,name:"",tiles:[],count:0})
                            objectName: "spaceMapTile"+space.id
                            Layout.fillWidth: true;Layout.minimumWidth:0
                            Layout.preferredWidth: 1
                            implicitHeight: Math.max(90,Theme.labelSize+Theme.detailSize+62)
                            padding: 7;quiet: true
                            Accessible.name: space.name+", "+space.count+(space.count===1 ? " window" : " windows")+(space.active ? ", current" : "")
                            Accessible.selected: map.selectedId===space.id
                            onClicked: {map.selectedId=space.id;map.moveWindowId="";}
                            Keys.onLeftPressed: map.focusTile(index-1)
                            Keys.onRightPressed: map.focusTile(index+1)
                            Keys.onUpPressed: map.focusTile(index-grid.columns)
                            Keys.onDownPressed: map.focusTile(index+grid.columns)
                            background: ControlSurface {
                                focused: card.activeFocus;hovered: card.hovered
                                pressed: card.visuallyDown;quiet: true
                                field: map.selectedId===card.space.id
                            }
                            contentItem: ColumnLayout {
                                spacing: 4
                                RowLayout {
                                    Layout.fillWidth:true;spacing:4
                                    Text {
                                        Layout.fillWidth:true;text:card.space.name;font.pixelSize:Theme.labelSize
                                        color:Theme.text;elide:Text.ElideRight;textFormat:Text.PlainText
                                    }
                                    Rectangle {visible:card.space.active;width:6;height:6;radius:3;color:Theme.accentInk}
                                }
                                Schematic {
                                    Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:32
                                    tiles:card.space.tiles
                                }
                                Text {
                                    Layout.fillWidth:true;text:card.space.count+(card.space.count===1 ? " window":" windows")
                                    color:Theme.muted;font.pixelSize:Theme.detailSize;elide:Text.ElideRight
                                }
                            }
                        }
                    }
                }
                RowLayout {
                    visible:map.page===0 && map.selected.id>=0;Layout.fillWidth:true
                    Text {
                        Layout.fillWidth:true;Layout.minimumWidth:0
                        text:map.selected.name || "";color:Theme.text;font.pixelSize:Theme.headingSize
                        font.weight:Font.DemiBold;elide:Text.ElideRight;textFormat:Text.PlainText
                    }
                    OrbitButton {
                        objectName:"spaceMapSwitch"
                        text:map.selected.active ? "Current space" : "Switch here"
                        enabled:!map.selected.active;accent:enabled
                        onClicked: {
                            if(Orbit.selectedOutput) Orbit.switchDesktopOn(map.selected.id,Orbit.selectedOutput);
                            else Orbit.switchDesktop(map.selected.id);
                            Orbit.dismiss();
                        }
                    }
                }
                Text {
                    visible: map.page===0 && !map.selected.count
                    Layout.fillWidth:true;wrapMode:Text.Wrap
                    text: map.spaces.length ? "No windows in this space." : "No workspaces available."
                    color:Theme.muted;font.pixelSize:Theme.labelSize
                }
                Repeater {
                    model:map.page===0 ? map.selected.windows : []
                    delegate: ColumnLayout {
                        id: windowRow
                        required property var modelData
                        Layout.fillWidth:true;spacing:2
                        RowLayout {
                            Layout.fillWidth:true;spacing:4
                            Image {
                                source:Theme.iconSource(windowRow.modelData.icon);sourceSize:Qt.size(24,24)
                                fillMode:Image.PreserveAspectFit
                                Layout.preferredWidth:20;Layout.preferredHeight:20
                            }
                            OrbitButton {
                                Layout.fillWidth:true;Layout.minimumWidth:0
                                padding:4;quiet:true;text:windowRow.modelData.name
                                hint:windowRow.modelData.minimized ? "Restore minimized window" : "Focus window"
                                onClicked:Orbit.focusWindow(windowRow.modelData.id)
                            }
                            OrbitButton {
                                id: moveButton
                                objectName:"spaceMapMove"+windowRow.modelData.id
                                text:map.moveWindowId===windowRow.modelData.id ? "Cancel" : "Move…"
                                enabled:!windowRow.modelData.minimized && !Arrangements.busy
                                Accessible.name:text==="Cancel" ? "Cancel move" : "Move "+windowRow.modelData.name+" to another space"
                                onClicked:{
                                    map.moveWindowId=map.moveWindowId===windowRow.modelData.id ? "" : windowRow.modelData.id;
                                    if(map.moveWindowId)Qt.callLater(function(){
                                        const first=destinations.itemAt(0);
                                        if(first)first.forceActiveFocus(Qt.TabFocusReason);
                                    });
                                }
                            }
                        }
                        GridLayout {
                            Layout.fillWidth:true
                            columns:width>=Theme.fontSize(240) ? 3 : 1
                            visible:map.moveWindowId===windowRow.modelData.id
                            Repeater {
                                id: destinations
                                model:parent.visible ? map.spaces.filter(space => space.id!==map.selected.id) : []
                                delegate: OrbitButton {
                                    required property var modelData
                                    objectName:"spaceMapDestination"+modelData.id
                                    Layout.fillWidth:true;Layout.preferredWidth:1;text:modelData.name
                                    onClicked:map.finishMove(windowRow.modelData.id,modelData.id)
                                }
                            }
                        }
                    }
                }
                Text {
                    visible: map.page===0 && map.selected.count>map.selected.windows.length
                    text:"+"+(map.selected.count-map.selected.windows.length)+" more windows"
                    color:Theme.muted;font.pixelSize:Theme.detailSize
                }
                Text {
                    visible:map.page===1 && !Arrangements.checkpoints.length
                    Layout.fillWidth:true;wrapMode:Text.Wrap
                    text:"Moves and snaps made with Mellipi will appear here. Checkpoints are cleared when you sign out."
                    color:Theme.muted;font.pixelSize:Theme.labelSize
                }
                Repeater {
                    model:map.page===1 && !map.checkpointId ? Arrangements.checkpoints : []
                    delegate: OrbitButton {
                        required property var modelData
                        required property int index
                        objectName:"spaceCheckpoint"+index
                        Layout.fillWidth:true;Layout.minimumWidth:0
                        text:modelData.label+" · "+modelData.count+(modelData.count===1 ? " window" : " windows")
                        enabled:!Arrangements.busy
                        onClicked:map.openCheckpoint(modelData.id)
                    }
                }
                ColumnLayout {
                    visible:map.page===1 && !!map.checkpointId
                    Layout.fillWidth:true;spacing:Theme.rowGap
                    OrbitButton {id:checkpointBack;text:"Back to checkpoints";quiet:true;onClicked:map.checkpointId=""}
                    Text {
                        Layout.fillWidth:true;wrapMode:Text.Wrap;textFormat:Text.PlainText
                        text:map.checkpoint.label || "Checkpoint no longer available"
                        color:Theme.text;font.pixelSize:Theme.headingSize;font.weight:Font.DemiBold
                    }
                    OrbitButton {
                        objectName:"restoreSpaceCheckpoint";text:"Restore positions";accent:true
                        enabled:!Arrangements.busy && map.checkpoint.available>0
                        onClicked:Arrangements.restoreCheckpoint(map.checkpointId)
                    }
                    GridLayout {
                        Layout.fillWidth:true
                        visible:!!(map.checkpoint.spaces || []).length
                        columns:Math.max(1,Math.min(4,Math.floor(width/Theme.fontSize(110))))
                        Repeater {
                            model:map.page===1 ? map.checkpoint.spaces || [] : []
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth:true;Layout.preferredWidth:1
                                Schematic {Layout.fillWidth:true;implicitHeight:65;tiles:modelData.tiles}
                                Text {text:"Space "+modelData.workspace;color:Theme.muted;font.pixelSize:Theme.detailSize}
                            }
                        }
                    }
                    Repeater {
                        model:map.page===1 ? map.checkpoint.rows || [] : []
                        delegate: Text {
                            required property var modelData
                            Layout.fillWidth:true;wrapMode:Text.Wrap;textFormat:Text.PlainText
                            text:modelData.name+" · Space "+modelData.workspace+" · "+modelData.status
                            color:modelData.available ? Theme.text : Theme.muted;font.pixelSize:Theme.labelSize
                        }
                    }
                }
            }
        }
        OrbitButton {
            visible:map.page===1 && !!Arrangements.undoLabel
            objectName:"spaceMapUndo";text:"Undo "+Arrangements.undoLabel
            Layout.fillWidth:true;Layout.minimumWidth:0
            enabled:!Arrangements.busy;onClicked:Arrangements.undo()
        }
    }
}
