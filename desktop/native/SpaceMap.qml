import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import "."
import "SettingReveal.js" as SettingReveal

FocusScope {
    id: map
    objectName: "spaceMap"
    property var spaces: []
    property string snapshotSignature: ""
    property int selectedId: -1
    property int page: 0
    property string checkpointId: ""
    property int renamingSpace: -1
    onSelectedIdChanged: renamingSpace=-1
    readonly property bool hasMovableWindows: spaces.some(space => space.windows.some(row => !row.minimized))
    property var dragOwner: null
    property var draggedWindow: null
    property int dragSourceId: -1
    property point dragPosition
    readonly property int workspaceColumns: width-4 >= Theme.fontSize(490) ? 4 : 2
    readonly property bool compactTargets: height < (workspaceColumns===4 ? 305 : 395)
        + Math.round(40*Math.max(0,Theme.textScale-1))
    readonly property bool shortTabs: width < Theme.fontSize(320)
    readonly property int dragTargetId: dragOwner ? dropTarget(dragPosition) : -1
    readonly property var selected: spaces.find(space => space.id===selectedId) || ({windows:[],id:-1,count:0,active:false,name:""})
    readonly property var checkpoint: {
        const revision=Arrangements.checkpoints;
        const topology=map.spaces;
        return map.checkpointId ? Arrangements.checkpointPreview(map.checkpointId) : ({});
    }
    function refresh() {
        // Replacing a QML repeater model destroys its drag handlers. Keep the
        // source stable for the gesture; the bridge verifies it again on drop.
        if(dragOwner)return;
        const latest=Orbit.spaceMapSnapshot();
        const signature=JSON.stringify(latest);
        if(signature===snapshotSignature)return;
        snapshotSignature=signature;
        if(!latest.some(space => space.id===selectedId)) {
            const active=latest.find(space => space.active) || latest[0];
            selectedId=active ? active.id : -1;
        }
        spaces=latest;
    }
    function dropTarget(scenePoint) {
        const clip=grid.mapFromItem(null,scenePoint.x,scenePoint.y);
        if(!grid.visible || !grid.contains(clip))return -1;
        for(let i=0;i<spaceTiles.count;i++){
            const card=spaceTiles.itemAt(i);
            if(!card || !card.visible || !card.enabled || card.space.id===dragSourceId)continue;
            const point=card.mapFromItem(null,scenePoint.x,scenePoint.y);
            if(card.contains(point))return card.space.id;
        }
        return -1;
    }
    function startDrag(owner,window,source,scenePoint) {
        if(dragOwner || page!==0)return;
        Orbit.hideTooltip();
        draggedWindow=window;
        dragSourceId=source;
        dragPosition=scenePoint;
        dragOwner=owner;
    }
    function updateDrag(owner,scenePoint) {
        if(dragOwner===owner)dragPosition=scenePoint;
    }
    function cancelDrag(owner) {
        if(!dragOwner || (owner && dragOwner!==owner))return;
        dragOwner=null;
        draggedWindow=null;
        dragSourceId=-1;
        Qt.callLater(refresh);
    }
    function releaseDrag(owner,scenePoint) {
        if(dragOwner!==owner || !draggedWindow)return;
        const ident=draggedWindow.id;
        const source=dragSourceId;
        const target=dropTarget(scenePoint);
        cancelDrag(owner);
        if(page===0 && target>=0 && !Arrangements.busy)
            Orbit.moveSpaceWindow(ident,source,target);
    }
    Keys.onEscapePressed: event => {
        event.accepted=!!dragOwner || !!checkpointId;
        if(dragOwner)cancelDrag(dragOwner);
        else if(checkpointId)closeCheckpoint();
    }
    Connections {
        target:map.Window.window
        function onActiveFocusItemChanged() {
            Qt.callLater(function(){
                const window=map.Window.window;
                if(window && viewport.visible)SettingReveal.scrollTo(viewport,window.activeFocusItem,6);
            });
        }
    }
    function focusTile(index) {
        const tile=spaceTiles.itemAt(index);
        if(tile){selectedId=tile.space.id;tile.forceActiveFocus(Qt.TabFocusReason);}
    }
    function finishRename() {
        renamingSpace=-1;Qt.callLater(focusSelected);
    }
    function focusSelected() {
        if(page===0)focusTile(Math.max(0,spaces.findIndex(space => space.id===selectedId)));
    }
    function openSpace(id) {
        const space=spaces.find(row => row.id===id);
        if(!space)return;
        if(!space.active) {
            if(Orbit.selectedOutput)Orbit.switchDesktopOn(id,Orbit.selectedOutput);
            else Orbit.switchDesktop(id);
        }
        Orbit.dismiss();
    }
    function keyboardMove(window,step) {
        if(window.minimized || Arrangements.busy)return;
        const source=selectedId;
        const index=spaces.findIndex(space=>space.id===source);
        const destination=spaces[index+step];
        if(destination && Orbit.moveSpaceWindow(window.id,source,destination.id))
            Qt.callLater(focusSelected);
    }
    function focusCheckpointBack() {
        if(checkpointId)checkpointBack.forceActiveFocus(Qt.TabFocusReason);
    }
    function closeCheckpoint() {
        const ident=checkpointId;
        checkpointId="";
        Qt.callLater(function(){
            for(let i=0;i<checkpointRows.count;i++){
                const row=checkpointRows.itemAt(i);
                if(row && row.modelData.id===ident){row.forceActiveFocus(Qt.TabFocusReason);return;}
            }
            recentTab.forceActiveFocus(Qt.TabFocusReason);
        });
    }
    function openCheckpoint(ident) {
        checkpointId=ident;
        Qt.callLater(focusCheckpointBack);
    }
    function showPage(index) {
        if(page===index)return;
        cancelDrag(dragOwner);
        page=index;
        checkpointId="";
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
        property int sourceSpace: -1
        radius:Theme.corner(5);color:Theme.background;clip:true
        Repeater {
            model: diagram.tiles
            delegate: Rectangle {
                required property var modelData
                objectName: diagram.sourceSpace>=0 ? "spaceMapDiagramWindow"+modelData.id : ""
                x:modelData.tile.x*diagram.width;y:modelData.tile.y*diagram.height
                width:Math.max(2,modelData.tile.w*diagram.width-1)
                height:Math.max(2,modelData.tile.h*diagram.height-1)
                opacity:modelData.available===false ? .43 : 1
                color:Theme.selectedSurface;radius:Theme.corner(3)
                border.width:1;border.color:Theme.controlBorder
                SpaceWindowDrag {
                    spaceMap:map
                    windowData:parent.modelData
                    sourceSpace:diagram.sourceSpace
                }
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
            id: mapTabs
            Layout.fillWidth: true
            columns: renameButton.visible ? 4 : 3
            columnSpacing: Theme.rowGap;rowSpacing: 4
            OrbitButton {Layout.fillWidth:true;Layout.minimumWidth:0;Layout.preferredWidth:1;text:"Spaces";accent:map.page===0;onClicked:map.showPage(0)}
            OrbitButton {Layout.fillWidth:true;Layout.minimumWidth:0;Layout.preferredWidth:1;id:recentTab;objectName:"spaceMapCheckpoints";text:map.shortTabs ? "Recent" : "Recent changes";Accessible.name:"Recent changes";accent:map.page===1;onClicked:map.showPage(1)}
            OrbitButton {Layout.fillWidth:true;Layout.minimumWidth:0;Layout.preferredWidth:1;objectName:"spaceMapSavedLayouts";text:map.shortTabs ? "Saved" : "Saved layouts";Accessible.name:"Saved layouts";accent:map.page===2;onClicked:map.showPage(2)}
            IconButton {
                id:renameButton
                objectName:"spaceMapRename";visible:map.page===0 && map.renamingSpace<0 && map.selected.id>=0 && map.selected.id<4
                iconName:"document-edit";hint:"Rename selected space"
                onClicked:{map.renamingSpace=map.selected.id;nameField.text=map.selected.customName || "";nameField.forceActiveFocus();nameField.selectAll();}
            }
        }
        RowLayout {
            visible:map.page===0 && map.renamingSpace===map.selected.id && map.selected.id>=0
            Layout.fillWidth:true
            function save(){if(Orbit.renameSpace(map.renamingSpace,nameField.text))map.finishRename();}
            OrbitField {
                id:nameField;objectName:"spaceMapNameField";Layout.fillWidth:true
                Layout.minimumWidth:0;maximumLength:32;placeholderText:"Space "+(map.selected.id+1)
                Accessible.name:"Space name"
                onAccepted:parent.save()
                Keys.onEscapePressed: event=>{map.finishRename();event.accepted=true;}
            }
            OrbitButton {objectName:"spaceMapSaveName";text:"Save";onClicked:parent.save()}
            OrbitButton {text:"Cancel";onClicked:map.finishRename()}
        }
        Loader {
            active: map.page===2;visible: active
            Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:0
            sourceComponent: Component {LayoutsPanel {}}
        }
        ColumnLayout {
            id: workspaceTargets
            visible:map.page===0
            Layout.fillWidth:true
            spacing: Theme.rowGap
            Text {
                visible:!map.compactTargets && map.spaces.length>1 && map.hasMovableWindows
                Layout.fillWidth:true;wrapMode:Text.Wrap
                text:"Drag a window onto another space to move it."
                color:Theme.muted;font.pixelSize:Theme.detailSize
            }
            GridLayout {
                id: grid
                visible: map.page===0
                Layout.fillWidth: true
                columns: map.workspaceColumns
                columnSpacing: Theme.rowGap;rowSpacing: Theme.rowGap
                Repeater {
                    id: spaceTiles
                    model: map.page===0 ? map.spaces.length : 0
                    delegate: OrbitButton {
                        id: card
                        readonly property bool receiving: map.dragTargetId===space.id
                        readonly property bool origin: !!map.dragOwner && map.dragSourceId===space.id
                        required property int index
                        readonly property var space: map.spaces[index] || ({id:-1,name:"",tiles:[],count:0})
                        objectName: "spaceMapTile"+space.id
                        Layout.fillWidth: true;Layout.minimumWidth:0
                        Layout.preferredWidth: 1
                        implicitHeight: map.compactTargets ? Math.max(50,Theme.labelSize+32) : Math.max(90,Theme.labelSize+Theme.detailSize+62)
                        padding: map.compactTargets ? 4 : 7;quiet: true
                        Accessible.name: space.name+", "+space.count+(space.count===1 ? " window" : " windows")+(space.active ? ", current" : "")
                        Accessible.selected: map.selectedId===space.id
                        hint:"Double-click or press Enter to open "+space.name
                        onClicked: map.selectedId=space.id
                        onDoubleClicked:if(!map.dragOwner)map.openSpace(space.id)
                        Accessible.onPressAction:map.openSpace(space.id)
                        Keys.onReturnPressed: event => {if(!event.isAutoRepeat)map.openSpace(card.space.id);}
                        Keys.onEnterPressed: event => {if(!event.isAutoRepeat)map.openSpace(card.space.id);}
                        Keys.onLeftPressed: map.focusTile(index-1)
                        Keys.onRightPressed: map.focusTile(index+1)
                        Keys.onUpPressed: map.focusTile(index-grid.columns)
                        Keys.onDownPressed: map.focusTile(index+grid.columns)
                        background: ControlSurface {
                            focused: card.activeFocus || card.receiving
                            primary: card.receiving
                            animate: true
                            hovered: card.hovered
                            pressed: card.visuallyDown
                            field: !card.receiving && (map.selectedId===card.space.id || !!map.dragOwner)
                            quiet: false
                            border.width: card.activeFocus || card.receiving ? 2 : 1
                            border.color: card.activeFocus ? Theme.focusColor
                                : card.receiving ? Theme.accentText : Theme.border
                            opacity: card.origin ? .66 : 1
                        }
                        contentItem: ColumnLayout {
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth:true;spacing:4
                                Text {
                                    Layout.fillWidth:true;text:card.space.name;font.pixelSize:Theme.labelSize
                                    color:map.dragTargetId===card.space.id ? Theme.accentText : Theme.text
                                    elide:Text.ElideRight;textFormat:Text.PlainText
                                }
                                Rectangle {visible:card.space.active && !card.receiving;width:6;height:6;radius:3;color:Theme.accentInk}
                                Image {
                                    visible:card.receiving
                                    Layout.preferredWidth:14;Layout.preferredHeight:14
                                    sourceSize:Qt.size(20,20)
                                    source:visible ? Theme.symbolicIconSource("go-down",Theme.accentText) : ""
                                }
                            }
                            Schematic {
                                Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:map.compactTargets ? 12 : 32
                                visible:card.space.tiles.length>0
                                tiles:card.space.tiles
                                sourceSpace:card.space.id
                                opacity:card.receiving ? .65 : 1
                            }
                            Text {
                                Layout.fillWidth:true
                                visible:!map.compactTargets
                                text:card.receiving ? "Drop here" : card.space.count+(card.space.count===1 ? " window":" windows")
                                color:map.dragTargetId===card.space.id ? Theme.accentText : Theme.muted
                                font.pixelSize:Theme.detailSize;elide:Text.ElideRight
                            }
                        }
                    }
                }
            }
        }
        ScrollView {
            id: viewport
            objectName: "spaceMapWindowViewport"
            visible: map.page!==2
            Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 0
            clip: true;contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: viewport.availableWidth-4;spacing: Theme.rowGap
                RowLayout {
                    visible:map.page===0 && map.selected.id>=0;Layout.fillWidth:true;spacing:Theme.rowGap
                    Text {
                        Layout.fillWidth:true;Layout.minimumWidth:0
                        text:map.selected.name || "";color:Theme.text;font.pixelSize:Theme.headingSize
                        font.weight:Font.DemiBold;elide:Text.ElideRight;textFormat:Text.PlainText
                        Accessible.name:text+(map.selected.active ? ", current space" : "")
                    }
                    Text {
                        visible:map.selected.active
                        text:"Current space";color:Theme.muted;font.pixelSize:Theme.detailSize
                    }
                }
                Text {
                    visible: map.page===0 && !map.selected.count
                    Layout.fillWidth:true;wrapMode:Text.Wrap
                    text: !map.spaces.length ? "No workspaces available."
                          : map.hasMovableWindows ? "No windows in this space."
                          : "Open an app to see its window here."
                    color:Theme.muted;font.pixelSize:Theme.labelSize
                }
                Repeater {
                    model:map.page===0 ? map.selected.windows : []
                    delegate: OrbitButton {
                        id: windowRow
                        required property var modelData
                        readonly property bool movable: !modelData.minimized && map.spaces.length>1 && !Arrangements.busy
                        readonly property bool lifting: !!map.draggedWindow && map.draggedWindow.id===modelData.id
                        objectName:"spaceMapWindow"+modelData.id
                        text:modelData.name
                        Layout.fillWidth:true;Layout.minimumWidth:0
                        implicitHeight:Math.max(32,Theme.labelSize+14)
                        padding:6;quiet:true
                        opacity:lifting ? .52 : 1
                        hint:movable ? "Drag to another space · ←/→" : modelData.minimized ? "Restore minimized window" : "Focus window"
                        onClicked:Orbit.focusWindow(modelData.id)
                        Keys.onPressed: event => {
                            if(!movable || event.modifiers!==Qt.NoModifier || (event.key!==Qt.Key_Left && event.key!==Qt.Key_Right))return;
                            event.accepted=true;
                            if(!event.isAutoRepeat)map.keyboardMove(modelData,event.key===Qt.Key_Left ? -1 : 1);
                        }
                        contentItem: RowLayout {
                            spacing:8
                            DragGrip {visible:windowRow.movable;Layout.preferredWidth:12}
                            Image {
                                source:Theme.iconSource(windowRow.modelData.icon);sourceSize:Qt.size(24,24)
                                fillMode:Image.PreserveAspectFit
                                Layout.preferredWidth:20;Layout.preferredHeight:20
                            }
                            Text {
                                Layout.fillWidth:true;Layout.minimumWidth:0
                                text:windowRow.text;textFormat:Text.PlainText;elide:Text.ElideRight
                                font:windowRow.font;color:Theme.text
                            }
                        }
                        SpaceWindowDrag {
                            spaceMap:map
                            windowData:windowRow.modelData
                            sourceSpace:windowRow.movable ? map.selectedId : -1
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
                    text:"Window moves and snaps appear here until you sign out. Select a change to preview its previous layout."
                    color:Theme.muted;font.pixelSize:Theme.labelSize
                }
                Repeater {
                    id:checkpointRows
                    model:map.page===1 ? Arrangements.checkpoints : []
                    delegate: OrbitButton {
                        required property var modelData
                        required property int index
                        objectName:"spaceCheckpoint"+index
                        visible:!map.checkpointId
                        Layout.fillWidth:true;Layout.minimumWidth:0
                        text:modelData.label+" · "+modelData.count+(modelData.count===1 ? " window" : " windows")
                        enabled:!Arrangements.busy
                        onClicked:map.openCheckpoint(modelData.id)
                    }
                }
                ColumnLayout {
                    visible:map.page===1 && !!map.checkpointId
                    Layout.fillWidth:true;spacing:Theme.rowGap
                    OrbitButton {id:checkpointBack;text:"Back to recent changes";quiet:true;onClicked:map.closeCheckpoint()}
                    Text {
                        Layout.fillWidth:true;wrapMode:Text.Wrap;textFormat:Text.PlainText
                        text:map.checkpoint.label || "This change is no longer available"
                        color:Theme.text;font.pixelSize:Theme.headingSize;font.weight:Font.DemiBold
                    }
                    OrbitButton {
                        objectName:"restoreSpaceCheckpoint";text:"Restore previous positions";accent:true
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
        RowLayout {
            visible:map.page!==2 && !!Arrangements.undoLabel
            Layout.fillWidth:true;spacing:Theme.rowGap
            Text {
                Layout.fillWidth:true;Layout.minimumWidth:0
                text:Arrangements.undoLabel;elide:Text.ElideRight;textFormat:Text.PlainText
                color:Theme.muted;font.pixelSize:Theme.detailSize
            }
            OrbitButton {
                objectName:"spaceMapUndo";text:"Undo"
                hint:"Undo "+Arrangements.undoLabel
                enabled:!Arrangements.busy;onClicked:Arrangements.undo()
            }
        }
    }
    Rectangle {
        id: dragPreview
        objectName: "spaceMapDragPreview"
        visible: !!map.dragOwner && !!map.draggedWindow
        z: 10
        readonly property point cursor: map.mapFromItem(null,map.dragPosition.x,map.dragPosition.y)
        readonly property var destination: map.spaces.find(space => space.id===map.dragTargetId)
        width: Math.min(map.width,Theme.fontSize(230))
        height: dragContents.implicitHeight+14
        x: Math.max(0,Math.min(map.width-width,cursor.x+12))
        y: Math.max(0,cursor.y+height+12<=map.height ? cursor.y+12 : cursor.y-height-12)
        color: Theme.raised
        border.color: dragPreview.destination ? Theme.accentInk : Theme.controlBorder
        border.width: 1
        radius: Theme.corner(6)
        RowLayout {
            id: dragContents
            anchors.fill: parent
            anchors.margins: 7
            Image {
                Layout.preferredWidth: 18;Layout.preferredHeight: 18
                source: dragPreview.visible ? Theme.iconSource(map.draggedWindow.icon) : ""
                sourceSize: Qt.size(24,24)
                fillMode: Image.PreserveAspectFit
            }
            Text {
                Layout.fillWidth: true;Layout.minimumWidth: 0
                text: !dragPreview.visible ? "" : map.draggedWindow.name
                textFormat: Text.PlainText
                color: Theme.text
                font.pixelSize: Theme.labelSize
                elide: Text.ElideRight
            }
        }
    }
}
