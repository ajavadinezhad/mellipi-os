import QtQuick 2.15
import QtQuick.Controls 2.15
import "."
Item {
    id: icons
    property var controller: null
    property real originX: 0
    property real originY: 0
    property string outputId: "default"
    property string selectedPath: ""
    property var selectedPaths: []
    readonly property color selectionBlue: "#3584e4"
    readonly property int baseIconSize: Theme.extraCompact ? 32 : Theme.compact ? 36 : 44
    readonly property int iconSize: Math.round(baseIconSize*(Orbit.appearance.desktopIconScale || 100)/100)
    readonly property int iconCell: (Theme.extraCompact ? 80 : Theme.compact ? 96 : 112) + iconSize - baseIconSize
    property var positions: ({})
    property string editingPath: ""
    property bool creatingFolder: false
    signal contextRequested(string path,int x,int y)
    signal interacted()
    readonly property var transfer:controller && typeof controller.transferState!=="undefined" ? controller.transferState : ({})
    readonly property var fileInfo:controller && typeof controller.filePanel!=="undefined" ? controller.filePanel : ({})
    readonly property bool editorActive:editBox.visible || fileDialog.visible || (transferCard.visible && !!transfer.conflict)
    signal editFocusRequested(string outputId,bool active)
    onSelectedPathsChanged:if(controller && typeof controller.setSelection==="function")controller.setSelection(selectedPaths)
    onEditorActiveChanged:editFocusRequested(outputId,editorActive)
    function clearSelection(){selectedPaths=[];selectedPath="";grid.focusedPath="";grid.currentIndex=-1;}
    function selectOne(path){selectedPaths=[path];selectedPath=path;}
    function selectItem(path,index,modifiers,rightClick){
        grid.changingSelection=true;grid.focusedPath=path;grid.currentIndex=index;grid.changingSelection=false;
        if(rightClick && selectedPaths.indexOf(path)>=0)return;
        if(modifiers & Qt.ControlModifier){var paths=selectedPaths.slice();var at=paths.indexOf(path);if(at>=0)paths.splice(at,1);else paths.push(path);selectedPaths=paths;selectedPath=paths.length ? paths[0] : "";}
        else selectOne(path);
    }
    function dragPaths(path){return selectedPaths.indexOf(path)>=0 ? selectedPaths.filter(p=>p.indexOf("orbit-place:")!==0) : [path];}
    function dragUris(path){return dragPaths(path).map(p=>grid.model.find(row=>row.path===p)).filter(row=>row && row.url && row.url.indexOf("file:")===0).map(row=>row.url).join("\r\n");}
    function focusedTile(){
        if(!grid.focusedPath)return null;
        const index=grid.model.findIndex(row=>row.path===grid.focusedPath);
        const t=index<0 ? null : repeater.itemAt(index);
        return t && t.visible ? t : null;
    }
    function reconcileSelection(){
        const paths=new Set(grid.model.map(row=>row.path));
        const retained=selectedPaths.filter(path=>paths.has(path));
        if(retained.length!==selectedPaths.length){selectedPaths=retained;selectedPath=retained[0] || "";}
        grid.changingSelection=true;
        grid.currentIndex=grid.model.findIndex(row=>row.path===grid.focusedPath);
        if(grid.currentIndex<0)grid.focusedPath="";
        grid.changingSelection=false;
    }
    function navigate(dx,dy){
        const from=focusedTile();
        let best=-1,score=Infinity;
        for(let i=0;i<repeater.count;i++){
            const t=repeater.itemAt(i);
            if(!t || !t.visible)continue;
            const x=t.cell[0],y=t.cell[1];
            const forward=from ? (x-from.cell[0])*dx+(y-from.cell[1])*dy : 1;
            if(forward<=0)continue;
            const cross=from ? Math.abs((x-from.cell[0])*dy+(y-from.cell[1])*dx) : 0;
            const rank=from ? forward*forward+cross*cross*2 : y*grid.columns+x;
            if(rank<score){score=rank;best=i;}
        }
        if(best>=0 && best!==grid.currentIndex)grid.currentIndex=best;
    }
    property var dropPreview: ({})
    function previewPositions(paths,anchor,x,y) {
        if(!positions[anchor] || !paths.length || paths.some(path=>!positions[path])){dropPreview=({});return;}
        const origin=positions[anchor];
        const cells=paths.map(path=>positions[path]);
        const dx=Math.max(-Math.min(...cells.map(p=>p[0])),Math.min(Math.floor(x/grid.cellWidth)-origin[0],grid.columns-1-Math.max(...cells.map(p=>p[0]))));
        const dy=Math.max(-Math.min(...cells.map(p=>p[1])),Math.min(Math.floor(y/grid.cellHeight)-origin[1],grid.rows-1-Math.max(...cells.map(p=>p[1]))));
        const next={};
        if(dx || dy)paths.forEach(path=>{next[path]=[positions[path][0]+dx,positions[path][1]+dy];});
        dropPreview=next;
    }
    function dropPositions(paths,anchor,x,y){
        if(!controller || !paths.length)return false;
        return controller.movePositions(paths,anchor,outputId,grid.columns,grid.rows,
            Math.floor(x/grid.cellWidth),Math.floor(y/grid.cellHeight));
    }
    function fileKey(event){
        if(!controller)return;
        var ctrl=!!(event.modifiers & Qt.ControlModifier);
        if(ctrl && event.key===Qt.Key_A){selectedPaths=Object.keys(positions);selectedPath=selectedPaths.length ? selectedPaths[0] : "";event.accepted=true;}
        else if(ctrl && event.key===Qt.Key_C && typeof controller.copyFiles==="function"){controller.copyFiles(selectedPaths);event.accepted=true;}
        else if(ctrl && event.key===Qt.Key_X && typeof controller.cutFiles==="function"){controller.cutFiles(selectedPaths);event.accepted=true;}
        else if(ctrl && event.key===Qt.Key_V && typeof controller.pasteFiles==="function"){controller.pasteFiles();event.accepted=true;}
        else if(event.key===Qt.Key_Delete && typeof controller.trashFiles==="function"){controller.trashFiles(selectedPaths);event.accepted=true;}
        else if(event.key===Qt.Key_F2 && typeof controller.requestRename==="function"){
            const item=focusedTile();
            if(item && selectedPaths.length===1 && selectedPaths[0]===item.modelData.path)controller.requestRename(item.modelData.path);
            event.accepted=true;
        }
        else if(event.key===Qt.Key_Menu || (event.key===Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))){
            const item=focusedTile();
            if(item)requestContext(item.modelData.path,item,item.width/2,item.height/2);
            else requestContext("",icons,16,16);
            event.accepted=true;
        }
    }
    function selectRectangle(x,y,w,h){
        var paths=[];
        for(var i=0;i<repeater.count;i++){
            var item=repeater.itemAt(i);
            if(item && item.visible && item.x+item.width>x && item.x<x+w && item.y+item.height>y && item.y<y+h)paths.push(item.modelData.path);
        }
        selectedPaths=paths;selectedPath=paths.length ? paths[0] : "";
    }
    function requestContext(path,item,px,py){var point=item.mapToItem(null,px,py);contextRequested(path,Math.round(originX+point.x),Math.round(originY+point.y));}
    function activateCurrent(){const item=focusedTile();if(controller && item){interacted();controller.open(item.modelData.path);}}
    function updateLayout(){if(controller && typeof controller.layout==="function")positions=controller.layout(outputId,grid.columns,grid.rows);else positions=({});}
    function beginRename(path,name){editingPath=path;creatingFolder=false;editor.text=name;editBox.visible=true;editor.forceActiveFocus();editor.selectAll();}
    function beginNewFolder(){editingPath="";creatingFolder=true;editor.text="New folder";editBox.visible=true;editor.forceActiveFocus();editor.selectAll();}
    function commitEdit(){if(!editor.text.trim())return;if(creatingFolder)controller.newFolder(editor.text);else controller.rename(editingPath,editor.text);editBox.visible=false;grid.forceActiveFocus();}
    onOutputIdChanged: updateLayout()
    Component.onCompleted: updateLayout()
    Connections {
        target: icons.controller;ignoreUnknownSignals:true
        function onChanged(){icons.updateLayout();}
        function onEditRequested(path,name){icons.beginRename(path,name);}
        function onFolderRequested(){icons.beginNewFolder();}
    }
    MouseArea {
        id:selectionArea;objectName:"desktopSelectionArea"
        anchors.fill: parent;acceptedButtons: Qt.LeftButton | Qt.RightButton
        property real startX:0
        property real startY:0
        property bool selecting:false
        property bool moved:false
        onPressed:mouse=>{
            icons.interacted();icons.clearSelection();grid.forceActiveFocus();
            startX=mouse.x;startY=mouse.y;moved=false;selecting=mouse.button===Qt.LeftButton;
        }
        onPositionChanged:mouse=>{
            if(!selecting)return;
            var px=Math.max(0,Math.min(width,mouse.x)),py=Math.max(0,Math.min(height,mouse.y));
            moved=moved || Math.abs(px-startX)>4 || Math.abs(py-startY)>4;
            selectionBox.x=Math.min(startX,px);selectionBox.y=Math.min(startY,py);
            selectionBox.width=Math.abs(px-startX);selectionBox.height=Math.abs(py-startY);
            if(moved)icons.selectRectangle(selectionBox.x,selectionBox.y,selectionBox.width,selectionBox.height);
        }
        onReleased:selecting=false
        onCanceled:{selecting=false;icons.clearSelection();}
        onClicked:mouse=>{if(mouse.button===Qt.RightButton)icons.requestContext("",this,mouse.x,mouse.y);}
    }
    DropArea {
        anchors.fill:parent
        onEntered: drag => {if(!drag.hasUrls && !(drag.source && drag.source.desktopPath))drag.accepted=false;}
        onPositionChanged: drag => {if(drag.source && drag.source.desktopPath)icons.previewPositions(drag.source.dragSelection,drag.source.desktopPath,drag.x,drag.y);}
        onExited:icons.dropPreview=({})
        onDropped: drop => {icons.dropPreview=({});if(drop.source && drop.source.desktopPath){drop.source.dragHandled=true;if(icons.dropPositions(drop.source.dragSelection,drop.source.desktopPath,drop.x,drop.y))drop.accept(Qt.MoveAction);else drop.accepted=false;return;}if(drop.hasUrls && icons.controller && typeof icons.controller.dropUrls==="function"){icons.controller.dropUrls(drop.urls.map(String));drop.accept(Qt.CopyAction);}}
    }
    Item {
        id:grid;objectName:"desktopIconsGrid";anchors.fill:parent
        property var model: icons.controller ? icons.controller.items : []
        readonly property int count:model.length
        readonly property int columns:Math.max(1,Math.floor(width/icons.iconCell))
        readonly property int rows:Math.max(1,Math.floor(height/icons.iconCell))
        readonly property real cellWidth:width/columns
        readonly property real cellHeight:icons.iconCell
        property int currentIndex:-1
        property string focusedPath:""
        property bool changingSelection:false
        activeFocusOnTab:count>0
        onColumnsChanged:icons.updateLayout()
        onRowsChanged:icons.updateLayout()
        onModelChanged:{icons.updateLayout();icons.reconcileSelection();}
        Keys.onReturnPressed:icons.activateCurrent()
        Keys.onEnterPressed:icons.activateCurrent()
        Keys.onEscapePressed:icons.clearSelection()
        Keys.onLeftPressed:icons.navigate(-1,0)
        Keys.onRightPressed:icons.navigate(1,0)
        Keys.onUpPressed:icons.navigate(0,-1)
        Keys.onDownPressed:icons.navigate(0,1)
        Keys.onPressed:event=>icons.fileKey(event)
        onCurrentIndexChanged:if(!changingSelection && currentIndex>=0 && currentIndex<count){focusedPath=model[currentIndex].path;icons.selectOne(focusedPath);}
        Repeater {
            id:repeater;model:grid.model
            delegate:Item {
                id:tile
                required property var modelData
                required property int index
                readonly property string desktopPath:modelData.path
                property var dragSelection:[]
                property bool dragHandled:false
                readonly property var cell:icons.positions[modelData.path] || [index%grid.columns,Math.floor(index/grid.columns)]
                x:cell[0]*grid.cellWidth;y:cell[1]*grid.cellHeight
                width:grid.cellWidth;height:grid.cellHeight;visible:y+height<=grid.height
                z:hit.drag.active?2:0
                Rectangle {
                    id:visual
                    Drag.active: hit.drag.active && modelData.kind!=="place"
                    Drag.dragType: Drag.Automatic
                    Drag.source: tile
                    Drag.supportedActions: Qt.CopyAction | Qt.MoveAction
                    Drag.proposedAction: Qt.CopyAction
                    Drag.mimeData: ({"text/uri-list":icons.dragUris(modelData.path)})
                    Drag.hotSpot.x:width/2
                    Drag.hotSpot.y:icons.iconSize/2
                    Drag.onDragStarted:{tile.dragSelection=icons.dragPaths(modelData.path);tile.dragHandled=false;hit.wasDragged=true;}
                    Drag.onDragFinished: action=>{icons.dropPreview=({});if(action!==Qt.IgnoreAction)tile.dragHandled=true;visual.x=4;visual.y=2;}
                    x:4;y:2;width:parent.width-8;height:icons.iconCell-6;radius:Theme.corner(7)
                    readonly property bool selected: icons.selectedPaths.indexOf(modelData.path)>=0
                    color: !selected && hit.containsMouse ? Theme.hover : "transparent"
                    MotionValue {id:selectionFade;target:visual.selected ? 1 : 0;duration:Theme.desktopMotion}
                    Rectangle {
                        objectName: "desktopSelectionHighlight"
                        anchors.fill:parent;radius:parent.radius
                        visible:opacity>0;opacity:selectionFade.value
                        color:Qt.rgba(.208,.518,.894,.22);border.color:icons.selectionBlue
                    }
                    Item {
                        id: artwork
                        objectName: "desktopArtwork"
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: 8
                        width: icons.iconSize
                        height: width
                        readonly property bool nativeApp: modelData.kind === "launcher" &&
                            /^mellipi-(files|terminal|browser|editor|calculator|calendar|photos|pdf|software|media|disks|settings|monitor|recorder|desktop)$/.test(modelData.icon)
                        readonly property bool owned: modelData.kind === "place" || modelData.kind === "folder" || nativeApp
                        Rectangle {
                            anchors.fill: parent
                            visible: artwork.owned
                            radius: Theme.corner(Math.round(artwork.width*.24))
                            color: Theme.raised
                            border.width: Theme.highContrast ? 1 : 0
                            border.color: Theme.controlBorder
                        }
                        Image {
                            anchors.centerIn: parent
                            width: artwork.owned ? Math.round(artwork.width*.68) : artwork.width
                            height: width
                            source: artwork.nativeApp ? Theme.taskbarIconSource(modelData.icon, false)
                                : artwork.owned ? Theme.symbolicIconSource(modelData.icon, Theme.accentInk)
                                : Theme.iconSource(modelData.icon)
                            sourceSize: Qt.size(Math.max(40, width),Math.max(40, height))
                            fillMode: Image.PreserveAspectFit
                        }
                    }
                    Text{x:4;y:icons.iconSize+10;width:parent.width-8;height:Math.max(0,parent.height-y-1);text:modelData.name;textFormat:Text.PlainText;color:Theme.text;font.pixelSize:Theme.fontSize(11);horizontalAlignment:Text.AlignHCenter;wrapMode:Text.Wrap;maximumLineCount:2;elide:Text.ElideRight}
                    MouseArea {
                        id:hit;anchors.fill:parent;hoverEnabled:true;acceptedButtons:Qt.LeftButton|Qt.RightButton
                        property bool wasDragged:false
                        property bool pendingSelection:false
                        drag.target:pressedButtons===Qt.LeftButton?visual:null
                        drag.threshold:8
                        drag.minimumX:-tile.x+4;drag.maximumX:Math.max(4,grid.width-tile.x-visual.width-4)
                        drag.minimumY:-tile.y+2;drag.maximumY:Math.max(2,grid.height-tile.y-visual.height-2)
                        onPressed:mouse=>{wasDragged=false;tile.dragHandled=false;icons.interacted();pendingSelection=mouse.button===Qt.LeftButton && mouse.modifiers===Qt.NoModifier && icons.selectedPaths.length>1 && visual.selected;icons.selectItem(modelData.path,index,mouse.modifiers,pendingSelection || mouse.button===Qt.RightButton);tile.dragSelection=modelData.kind==="place" ? [modelData.path] : icons.dragPaths(modelData.path);grid.forceActiveFocus();}
                        onPositionChanged:if(drag.active)wasDragged=true
                        onReleased:mouse=>{
                            if(mouse.button===Qt.LeftButton && pendingSelection && !wasDragged)icons.selectOne(modelData.path);
                            if(mouse.button===Qt.LeftButton && wasDragged && !tile.dragHandled && icons.controller){
                                var column=Math.max(0,Math.min(grid.columns-1,Math.round((tile.x+visual.x-4)/grid.cellWidth)));
                                var row=Math.max(0,Math.min(grid.rows-1,Math.round((tile.y+visual.y-2)/grid.cellHeight)));
                                icons.dropPositions(tile.dragSelection,modelData.path,(column+.5)*grid.cellWidth,(row+.5)*grid.cellHeight);
                            }
                            visual.x=4;visual.y=2;
                        }
                        onCanceled:{visual.x=4;visual.y=2;}
                        onClicked:mouse=>{if(mouse.button===Qt.RightButton)icons.requestContext(modelData.path,hit,mouse.x,mouse.y);}
                        onDoubleClicked:mouse=>{if(mouse.button===Qt.LeftButton && !wasDragged)icons.controller.open(modelData.path);}
                    }
                    Accessible.name:modelData.name;Accessible.role:Accessible.Button
                    Accessible.onPressAction:{icons.interacted();icons.controller.open(modelData.path);}
                }
            }
        }
    }
    Repeater {
        model:Object.values(icons.dropPreview)
        Rectangle {
            required property var modelData
            x:modelData[0]*grid.cellWidth+4;y:modelData[1]*grid.cellHeight+2
            width:grid.cellWidth-8;height:grid.cellHeight-6
            z:3;radius:Theme.corner(7);border.color:Theme.accentInk
            color:Qt.rgba(Theme.accent.r,Theme.accent.g,Theme.accent.b,.18)
        }
    }
    Rectangle {
        id:selectionBox;objectName:"desktopSelectionBox";z:5
        visible:selectionArea.selecting && selectionArea.moved
        color:Qt.rgba(0.208,0.518,0.894,0.18);border.color:icons.selectionBlue;border.width:1
    }
    Rectangle {
        id:editBox;visible:false;anchors.centerIn:parent;width:Math.min(360,icons.width-24);height:form.implicitHeight+24;z:10;radius:Theme.corner(8);color:Theme.raised;border.color:Theme.accent
        Column {
            id:form;anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;anchors.margins:12;spacing:8
            Text {text:icons.creatingFolder?"New folder":"Rename item";color:Theme.text;font.pixelSize:Theme.fontSize(14)}
            OrbitField {
                id:editor;width:parent.width;implicitHeight:Math.max(34,Theme.fontSize(13)+14)
                maximumLength:200;Accessible.name:icons.creatingFolder?"Folder name":"File name"
                onAccepted:icons.commitEdit()
                Keys.onEscapePressed:{editBox.visible=false;grid.forceActiveFocus();}
            }
            Row {
                anchors.right:parent.right;spacing:8
                OrbitButton {text:"Cancel";quiet:true;onClicked:{editBox.visible=false;grid.forceActiveFocus();}}
                OrbitButton {text:icons.creatingFolder?"Create":"Rename";accent:true;onClicked:icons.commitEdit()}
            }
        }
    }
    Rectangle {
        id:transferCard;objectName:"desktopTransferCard";z:12
        visible:!!icons.transfer.message
        anchors.left:parent.left;anchors.bottom:parent.bottom;anchors.margins:8
        width:Math.min(420,icons.width-16);height:icons.transfer.conflict ? 148 : 104
        color:Theme.raised;border.color:Theme.border;radius:Theme.corner(8)
        Text {x:12;y:10;width:parent.width-50;text:icons.transfer.message || "";textFormat:Text.PlainText;color:Theme.text;font.pixelSize:Theme.fontSize(11);elide:Text.ElideMiddle}
        Text {x:12;y:34;width:parent.width-24;text:icons.transfer.conflict ? "Keep both creates a new name. Existing files stay unchanged." : (icons.transfer.files || 0)+" files · "+Math.round((icons.transfer.bytes || 0)/1048576*10)/10+" MiB";wrapMode:Text.Wrap;textFormat:Text.PlainText;color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
        Rectangle {visible:!icons.transfer.conflict && !!icons.transfer.busy;x:12;y:57;width:parent.width-24;height:3;color:Theme.background
            Rectangle {width:parent.width*Math.max(0,Math.min(1,icons.transfer.currentTotal ? icons.transfer.currentBytes/icons.transfer.currentTotal : 0));height:3;color:Theme.accent}
        }
        Row {x:12;y:icons.transfer.conflict ? 98 : 66;spacing:6
            OrbitButton {objectName:"desktopTransferKeepBoth";visible:!!icons.transfer.conflict;text:"Keep both";implicitWidth:104;implicitHeight:30;onClicked:icons.controller.resolveTransferConflict("keep-both")}
            OrbitButton {objectName:"desktopTransferSkip";visible:!!icons.transfer.conflict;text:"Skip";implicitWidth:72;implicitHeight:30;onClicked:icons.controller.resolveTransferConflict("skip")}
            OrbitButton {objectName:"desktopTransferCancel";visible:!!icons.transfer.busy;text:"Cancel";implicitWidth:78;implicitHeight:30;onClicked:icons.controller.cancelTransfer()}
        }
        IconButton {visible:!icons.transfer.busy;x:parent.width-32;y:5;width:26;height:26;iconName:"close";hint:"Dismiss transfer status";onClicked:icons.controller.clearTransferStatus()}
        Keys.onEscapePressed:if(icons.transfer.busy)icons.controller.cancelTransfer()
    }
    MouseArea {anchors.fill:parent;z:13;visible:fileDialog.visible;onClicked:icons.controller.closeFilePanel()}
    Rectangle {
        id:fileDialog;objectName:"desktopFileDialog";z:14;anchors.centerIn:parent
        visible:!!icons.fileInfo.kind;width:Math.min(400,icons.width-24);height:Math.min(icons.height-24,icons.fileInfo.kind==="open-with" ? 360 : 306)
        color:Theme.raised;border.color:Theme.border;radius:Theme.corner(8)
        Text {x:14;y:12;width:parent.width-54;text:icons.fileInfo.kind==="open-with" ? "Open with" : "Properties";color:Theme.text;font.pixelSize:Theme.fontSize(14)}
        IconButton {x:parent.width-35;y:8;width:27;height:27;iconName:"close";hint:"Close";onClicked:icons.controller.closeFilePanel()}
        Text {x:14;y:43;width:parent.width-28;text:icons.fileInfo.name || "";color:Theme.text;font.pixelSize:Theme.fontSize(12);elide:Text.ElideMiddle;textFormat:Text.PlainText}
        ListView {
            objectName:"desktopOpenWithApps";visible:icons.fileInfo.kind==="open-with";x:12;y:74;width:parent.width-24;height:parent.height-88;clip:true;cacheBuffer:0;reuseItems:true;spacing:4
            model:icons.fileInfo.apps || [];boundsBehavior:Flickable.StopAtBounds
            delegate:OrbitButton {required property var modelData;objectName:"desktopOpenWithChoice";width:ListView.view.width;implicitHeight:34;text:modelData.name;onClicked:icons.controller.chooseApplication(modelData.id)}
            Text {visible:parent.count===0;width:parent.width;wrapMode:Text.Wrap;text:"No installed applications can open this file.";color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }
        Column {
            visible:icons.fileInfo.kind==="properties";x:14;y:76;width:parent.width-28;spacing:10
            TextEdit {width:parent.width;height:Math.min(60,implicitHeight);readOnly:true;selectByMouse:true;wrapMode:TextEdit.Wrap;text:icons.fileInfo.path || "";color:Theme.muted;font.pixelSize:Theme.fontSize(10);textFormat:TextEdit.PlainText}
            Text {width:parent.width;text:(icons.fileInfo.type || "")+(icons.fileInfo.size ? " · "+icons.fileInfo.size : "");wrapMode:Text.Wrap;color:Theme.text;font.pixelSize:Theme.fontSize(11);textFormat:Text.PlainText}
            Text {width:parent.width;text:"Modified: "+(icons.fileInfo.modified || "");wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
            Text {width:parent.width;text:icons.fileInfo.permissions || "";color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
            Text {visible:!!icons.fileInfo.target;width:parent.width;text:"Links to: "+(icons.fileInfo.target || "");wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10);textFormat:Text.PlainText}
        }
        Keys.onEscapePressed:icons.controller.closeFilePanel()
    }

}
