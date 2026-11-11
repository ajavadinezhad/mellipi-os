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
    readonly property int iconCell: Theme.extraCompact ? 80 : Theme.compact ? 96 : 112
    readonly property int iconSize: Theme.extraCompact ? 32 : Theme.compact ? 36 : 44
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
    function clearSelection(){selectedPaths=[];selectedPath="";grid.currentIndex=-1;}
    function selectOne(path){selectedPaths=[path];selectedPath=path;}
    function selectItem(path,index,modifiers,rightClick){
        grid.changingSelection=true;grid.currentIndex=index;grid.changingSelection=false;
        if(rightClick && selectedPaths.indexOf(path)>=0)return;
        if(modifiers & Qt.ControlModifier){var paths=selectedPaths.slice();var at=paths.indexOf(path);if(at>=0)paths.splice(at,1);else paths.push(path);selectedPaths=paths;selectedPath=paths.length ? paths[0] : "";}
        else selectOne(path);
    }
    function dragPaths(path){return selectedPaths.indexOf(path)>=0 ? selectedPaths.filter(p=>p.indexOf("orbit-place:")!==0) : [path];}
    function dragUris(path){return dragPaths(path).map(p=>grid.model.find(row=>row.path===p)).filter(row=>row && row.url && row.url.indexOf("file:")===0).map(row=>row.url).join("\r\n");}
    function dropPositions(paths,x,y){
        if(!controller || typeof controller.setPosition!=="function" || !paths.length)return;
        var origin=positions[paths[0]] || [0,0];var column=Math.max(0,Math.min(grid.columns-1,Math.floor(x/grid.cellWidth))),row=Math.max(0,Math.min(grid.rows-1,Math.floor(y/grid.cellHeight)));
        var dx=column-origin[0],dy=row-origin[1];
        var old=Object.assign({},positions);
        paths.forEach(path=>{var point=old[path] || origin;controller.setPosition(path,outputId,Math.max(0,Math.min(grid.columns-1,point[0]+dx)),Math.max(0,Math.min(grid.rows-1,point[1]+dy)));});
    }
    function fileKey(event){
        if(!controller)return;
        var ctrl=!!(event.modifiers & Qt.ControlModifier);
        if(ctrl && event.key===Qt.Key_A){selectedPaths=grid.model.map(row=>row.path);selectedPath=selectedPaths.length ? selectedPaths[0] : "";event.accepted=true;}
        else if(ctrl && event.key===Qt.Key_C && typeof controller.copyFiles==="function"){controller.copyFiles(selectedPaths);event.accepted=true;}
        else if(ctrl && event.key===Qt.Key_X && typeof controller.cutFiles==="function"){controller.cutFiles(selectedPaths);event.accepted=true;}
        else if(ctrl && event.key===Qt.Key_V && typeof controller.pasteFiles==="function"){controller.pasteFiles();event.accepted=true;}
        else if(event.key===Qt.Key_Delete && typeof controller.trashFiles==="function"){controller.trashFiles(selectedPaths);event.accepted=true;}
        else if(event.key===Qt.Key_F2 && selectedPath && typeof controller.requestRename==="function"){controller.requestRename(selectedPath);event.accepted=true;}
        else if(event.key===Qt.Key_Menu || (event.key===Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))){
            var item=grid.currentIndex>=0 ? repeater.itemAt(grid.currentIndex) : null;
            if(item)requestContext(selectedPath,item,item.width/2,item.height/2);
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
    function activateCurrent(){if(controller && grid.currentIndex>=0 && grid.currentIndex<grid.count){interacted();controller.open(grid.model[grid.currentIndex].path);}}
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
        onDropped: drop => {if(drop.source && drop.source.desktopPath){drop.source.dragHandled=true;icons.dropPositions(drop.source.dragSelection,drop.x,drop.y);drop.accept(Qt.MoveAction);return;}if(drop.hasUrls && icons.controller && typeof icons.controller.dropUrls==="function"){icons.controller.dropUrls(drop.urls.map(String));drop.accept(Qt.CopyAction);}}
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
        property bool changingSelection:false
        activeFocusOnTab:count>0
        onColumnsChanged:icons.updateLayout()
        onRowsChanged:icons.updateLayout()
        onModelChanged:icons.updateLayout()
        Keys.onReturnPressed:icons.activateCurrent()
        Keys.onEnterPressed:icons.activateCurrent()
        Keys.onEscapePressed:icons.clearSelection()
        Keys.onLeftPressed:currentIndex=Math.max(0,currentIndex-1)
        Keys.onRightPressed:currentIndex=Math.min(count-1,currentIndex+1)
        Keys.onUpPressed:currentIndex=Math.max(0,currentIndex-columns)
        Keys.onDownPressed:currentIndex=Math.min(count-1,currentIndex+columns)
        Keys.onPressed:event=>icons.fileKey(event)
        onCurrentIndexChanged:if(!changingSelection && currentIndex>=0 && currentIndex<count)icons.selectOne(model[currentIndex].path)
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
                    Drag.onDragFinished: action=>{if(action!==Qt.IgnoreAction)tile.dragHandled=true;visual.x=4;visual.y=2;}
                    x:4;y:2;width:parent.width-8;height:icons.iconCell-6;radius:Theme.corner(7)
                    color:icons.selectedPaths.indexOf(modelData.path)>=0?Qt.rgba(0.208,0.518,0.894,0.22):hit.containsMouse?Theme.hover:"transparent"
                    border.color:icons.selectedPaths.indexOf(modelData.path)>=0?icons.selectionBlue:"transparent"
                    Image{anchors.horizontalCenter:parent.horizontalCenter;y:8;width:icons.iconSize;height:icons.iconSize;source:Theme.iconSource(modelData.icon);sourceSize:Qt.size(40,40);fillMode:Image.PreserveAspectFit}
                    Text{x:4;y:icons.iconSize+13;width:parent.width-8;height:Math.max(24,icons.iconCell-icons.iconSize-28);text:modelData.name;textFormat:Text.PlainText;color:Theme.text;font.pixelSize:Theme.fontSize(11);horizontalAlignment:Text.AlignHCenter;wrapMode:Text.Wrap;maximumLineCount:2;elide:Text.ElideRight}
                    MouseArea {
                        id:hit;anchors.fill:parent;hoverEnabled:true;acceptedButtons:Qt.LeftButton|Qt.RightButton
                        property bool wasDragged:false
                        drag.target:pressedButtons===Qt.LeftButton?visual:null
                        drag.threshold:8
                        drag.minimumX:-tile.x+4;drag.maximumX:Math.max(4,grid.width-tile.x-visual.width-4)
                        drag.minimumY:-tile.y+2;drag.maximumY:Math.max(2,grid.height-tile.y-visual.height-2)
                        onPressed:mouse=>{wasDragged=false;tile.dragHandled=false;icons.interacted();icons.selectItem(modelData.path,index,mouse.modifiers,mouse.button===Qt.RightButton);tile.dragSelection=icons.dragPaths(modelData.path);grid.forceActiveFocus();}
                        onPositionChanged:if(drag.active)wasDragged=true
                        onReleased:mouse=>{
                            if(mouse.button===Qt.LeftButton && wasDragged && !tile.dragHandled && icons.controller && typeof icons.controller.setPosition==="function"){
                                var column=Math.max(0,Math.min(grid.columns-1,Math.round((tile.x+visual.x-4)/grid.cellWidth)));
                                var row=Math.max(0,Math.min(grid.rows-1,Math.round((tile.y+visual.y-2)/grid.cellHeight)));
                                icons.controller.setPosition(modelData.path,icons.outputId,column,row);
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
