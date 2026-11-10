import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: launcher
    objectName: "unifiedLauncher"
    spacing: 10
    signal toolsRequested()
    property string query: ""
    property bool showLayouts: false
    property bool pinnedOnly: false
    property bool historyOptions: false
    property bool confirmHistoryReset: false
    onPinnedOnlyChanged: rebuild()
    property var results: []
    property string resultKey: ""
    onQueryChanged: rebuild()
    property bool viewReady: false
    property real viewOpacity: 1
    property real viewOffset: 0
    function settleView() {viewEnter.stop();viewOpacity=1;viewOffset=0;}
    onShowLayoutsChanged: {
        settleView();
        if(viewReady && !Theme.reducedMotion)viewEnter.restart();
        if(showLayouts) layoutsLoader.forceActiveFocus(); else Qt.callLater(focusSearch);
    }
    ParallelAnimation {
        id: viewEnter;objectName: "launcherViewTransition"
        NumberAnimation {target:launcher;property:"viewOpacity";from:.82;to:1;duration:Theme.motion;easing.type:Easing.OutCubic}
        NumberAnimation {target:launcher;property:"viewOffset";from:Theme.economy ? 0 : 4;to:0;duration:Theme.motion;easing.type:Easing.OutCubic}
        onStopped: {launcher.viewOpacity=1;launcher.viewOffset=0;}
    }
    readonly property bool motionDisabled:Theme.reducedMotion
    readonly property bool motionEconomy:Theme.economy
    onMotionDisabledChanged:if(motionDisabled)launcher.settleView();
    onMotionEconomyChanged:launcher.settleView();
    function rebuild() {
        var text=query.trim().toLowerCase(), words=text.split(/\s+/).filter(Boolean), rows=[], running={};
        function matches(value){var haystack=value.toLowerCase();return words.every(function(word){return haystack.indexOf(word)>=0;});}
        if(text) {
            function compact(value){return value.toLowerCase().replace(/[\s_-]+/g,"");}
            var actions=Orbit.systemActions || [], normalized=compact(text), actionRows=[];
            var loginTarget=actions.some(function(action){return action.id==="switch-user";}) ? "switch-user" : "session";
            var aliases={login:loginTarget,signin:loginTarget,signout:"logout",logoff:"logout",poweroff:"shutdown",turnoff:"shutdown"};
            actions.forEach(function(action,index){
                var exact=normalized===compact(action.id) || normalized===compact(action.name) || aliases[normalized]===action.id;
                if(exact || matches(action.searchText || [action.name,action.description,(action.keywords || []).join(" ")].join(" ")))
                    actionRows.push({action:action,rank:exact ? 0 : matches(action.name) ? 1 : 2,index:index});
            });
            actionRows.sort(function(a,b){return a.rank-b.rank || a.index-b.index;}).forEach(function(item){
                var action=item.action;
                rows.push({kind:"action",id:action.id,appId:"",name:action.name,description:action.description,icon:action.icon,category:"System actions"});
            });
        }
        var settingsAction=rows.some(function(row){return row.kind==="action" && row.id==="settings";});
        var settingsWindow=Orbit.windows.some(function(window){return ["orbit-settings","orbit-settings.desktop"].indexOf((window.klass || "").toLowerCase())>=0;});
        Orbit.dockApps.forEach(function(group){if(group.windows.length)running[group.id]=true;});
        Orbit.windows.forEach(function(window){
            if(settingsAction && ["orbit-settings","orbit-settings.desktop"].indexOf((window.klass || "").toLowerCase())>=0)return;
            if(Orbit.windowFilter && Orbit.windowFilter.length && Orbit.windowFilter.indexOf(String(window.id))<0)return;
            var group=Orbit.dockApps.find(function(app){return app.windows.some(function(w){return String(w.id)===String(window.id);});});
            if(pinnedOnly && (!group || Orbit.appearance.pins.indexOf(group.id)<0))return;
            var name=group ? group.name : window.klass || "Application";
            var metadata=Orbit.launcherApps.find(function(app){return group && app.id===group.id;});
            var terms=metadata ? metadata.searchText || [metadata.name,metadata.description,metadata.genericName || "",(metadata.keywords || []).join(" ")].join(" ") : "";
            if(!matches(name+" "+window.title+" "+terms))return;
            rows.push({kind:"window",id:String(window.id),appId:group ? group.id : "",name:window.title || name,description:name+" · "+(window.minimized ? "Minimized" : "Workspace "+(window.desktop+1)),icon:window.icon || "application-x-executable",category:"Open windows"});
        });
        Orbit.dockApps.filter(function(task){return task.id==="orbit-settings";}).forEach(function(task){
            if(!settingsAction && !settingsWindow && !pinnedOnly && matches(task.name+" settings preferences"))rows.push({kind:"task",id:task.id,appId:"",name:task.name,description:"Return to settings",icon:task.icon,category:"Open windows"});
        });
        Orbit.launcherApps.forEach(function(app){
            if(app.id==="orbit-settings.desktop" && (settingsAction || settingsWindow))return;
            if((pinnedOnly && Orbit.appearance.pins.indexOf(app.id)<0) || running[app.id] || !matches(app.searchText || [app.name,app.description,app.genericName || "",(app.keywords || []).join(" ")].join(" ")))return;
            rows.push({kind:"app",id:app.id,appId:app.id,name:app.name,description:app.description || "Launch application",icon:app.icon,category:"Applications"});
        });
        var key=JSON.stringify(rows);if(key!==resultKey){resultKey=key;results=rows;}
    }
    function activate(row){if(!row)return;if(showLayouts)return;if(row.kind==="action")Orbit.activateSystemAction(row.id);else if(row.kind==="task")Orbit.activateDock(row.id,false);else if(row.kind==="window")Orbit.focusWindow(row.id);else Orbit.launch(row.id);}
    function openResultMenu(index) {
        var row=results[index];if(!row || row.kind==="action")return false;
        var item=resultsList.itemAtIndex(index);if(!item)return false;
        Orbit.openPanelContext(item,row.kind==="task" ? "app" : row.kind,row.id,item.width/2,item.height/2);return true;
    }
    function focusSearch(){search.forceActiveFocus();}
    Component.onCompleted: {rebuild();viewReady=true;Qt.callLater(focusSearch);}
    Connections {
        target: Orbit;ignoreUnknownSignals: true
        function onWindowsChanged(){launcher.rebuild();}
        function onLauncherChanged(){launcher.rebuild();}
        function onChanged(){launcher.rebuild();}
        function onSettingsChanged(){launcher.rebuild();}
        function onSystemActionsChanged(){launcher.rebuild();}
    }
    RowLayout {
        Layout.fillWidth: true;spacing: 8
        OrbitField {
            visible: !launcher.showLayouts;id: search;objectName: "foldAppSearch";Layout.fillWidth: true;implicitHeight: 36
            placeholderText: "Search apps, windows or actions";font.pixelSize: Theme.fontSize(12)
            onTextChanged: launcher.query=text
            onAccepted: if(!launcher.showLayouts && launcher.results.length)launcher.activate(launcher.results[0])
            Keys.onDownPressed: if(!launcher.showLayouts && resultsList.count){resultsList.currentIndex=0;resultsList.forceActiveFocus();}
        }
        OrbitButton {text: launcher.showLayouts ? "Apps & windows" : "Saved layouts";enabled: Arrangements.available;implicitHeight:36;onClicked:launcher.showLayouts=!launcher.showLayouts}
        OrbitButton {objectName: "foldToolsButton";text: "Files & notes";implicitHeight: 36;hint: "Browse files and keep a local note";onClicked: launcher.toolsRequested()}
    }
    Text {visible:!launcher.showLayouts;text:"Sort apps";color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
    RowLayout {
        visible:!launcher.showLayouts
        Layout.fillWidth: true;spacing: 8
        OrbitButton {objectName: "launcherPinnedFilter";text: "Pinned apps";quiet: !launcher.pinnedOnly;implicitHeight: 28;hint: "Pinned apps and their open windows";onClicked: launcher.pinnedOnly=!launcher.pinnedOnly}
        SettingsSegments {
            objectName: "launcherSortOptions"
            value: Orbit.appearance.launcherSort || "frequent"
            segmentWidth: Math.max(76,Math.ceil(Theme.fontSize(11)*5.8))
            options: [{label:"Most used",value:"frequent"},{label:"Recent",value:"recent"},{label:"A–Z",value:"name"}]
            onSelected: value => Orbit.setPreference("launcherSort",value)
        }
        Item {Layout.fillWidth: true}
    }
    RowLayout {
        visible:!launcher.showLayouts && launcher.historyOptions;Layout.fillWidth:true
        Text {Layout.fillWidth:true;text:launcher.confirmHistoryReset ? "Clear app counts and recent ordering?" : "Application usage is stored locally.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
        OrbitButton {objectName:"launcherResetUsage";text:launcher.confirmHistoryReset ? "Clear history" : "Clear history…";implicitHeight:26;onClicked:{if(launcher.confirmHistoryReset){Orbit.clearLauncherHistory();launcher.confirmHistoryReset=false;launcher.historyOptions=false;}else launcher.confirmHistoryReset=true;}}
        OrbitButton {text:"Cancel";quiet:true;implicitHeight:26;onClicked:{launcher.historyOptions=false;launcher.confirmHistoryReset=false;}}
    }
    ListView {
        visible:!launcher.showLayouts
        opacity:launcher.viewOpacity;transform:Translate {y:launcher.viewOffset}
        id: resultsList;objectName: "unifiedResults";Layout.fillWidth: true;Layout.fillHeight: true
        model: launcher.results;clip: true;cacheBuffer: 0;reuseItems: true;spacing: 4
        boundsBehavior: Flickable.StopAtBounds;activeFocusOnTab: true;keyNavigationEnabled: true
        section.property: "category";section.criteria: ViewSection.FullString
        section.delegate: Text {width: resultsList.width;height: 29;verticalAlignment: Text.AlignVCenter;text: section;color: Theme.muted;font.pixelSize: Theme.fontSize(10)}
        onCountChanged: currentIndex=count ? Math.max(0,Math.min(currentIndex,count-1)) : -1
        Keys.onPressed:event=>{if(event.key===Qt.Key_Menu || (event.key===Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))){event.accepted=launcher.openResultMenu(currentIndex);}}
        Keys.onReturnPressed: launcher.activate(launcher.results[currentIndex])
        Keys.onEnterPressed: launcher.activate(launcher.results[currentIndex])
        Keys.onSpacePressed: launcher.activate(launcher.results[currentIndex])
        Keys.onUpPressed: {if(currentIndex<=0){search.forceActiveFocus();event.accepted=true;}else event.accepted=false;}
        delegate: Rectangle {
            id: result;objectName: "unifiedResult";required property var modelData;required property int index
            width: resultsList.width;height: Theme.extraCompact ? 44 : Theme.compact ? 56 : 68;radius: Theme.corner(5)
            color: hit.containsMouse ? Theme.hover : Theme.surface
            border.color: resultsList.activeFocus && resultsList.currentIndex===index ? Theme.focusColor : Theme.border
            onActiveFocusChanged:if(activeFocus)resultsList.currentIndex=index
            Accessible.role: Accessible.Button;Accessible.name: modelData.name;Accessible.description: modelData.description
            Accessible.onPressAction: launcher.activate(modelData)
            MouseArea {
                id: hit;anchors.fill: parent;hoverEnabled: true;acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: mouse => {resultsList.currentIndex=index;if(mouse.button===Qt.RightButton){if(modelData.kind!=="action")Orbit.openPanelContext(hit,modelData.kind==="task" ? "app" : modelData.kind,modelData.id,mouse.x,mouse.y);}else launcher.activate(modelData);}
            }
            RowLayout {
                anchors.fill: parent;anchors.margins: Theme.extraCompact ? 6 : Theme.compact ? 9 : 12;spacing: Theme.extraCompact ? 7 : 10
                Image {Layout.preferredWidth: 26;Layout.preferredHeight: 26;source: "image://icons/"+modelData.icon;sourceSize: Qt.size(32,32);fillMode: Image.PreserveAspectFit}
                ColumnLayout {
                    Layout.fillWidth: true;Layout.minimumWidth: 0;spacing: 3
                    Text {text: modelData.name;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.text;font.pixelSize: Theme.fontSize(12);textFormat: Text.PlainText}
                    Text {text: modelData.description;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.muted;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText}
                }
                IconButton {objectName: "unifiedPin";onActiveFocusChanged:if(activeFocus)resultsList.currentIndex=result.index;visible: !!modelData.appId;iconName: Orbit.appearance.pins.indexOf(modelData.appId)>=0 ? "pinned" : "pin";hint: Orbit.appearance.pins.indexOf(modelData.appId)>=0 ? "Unpin app" : "Pin app";accessibleLabel: hint+" · "+modelData.name;implicitWidth: 26;implicitHeight: 26;onClicked: Orbit.togglePin(modelData.appId)}
            }
        }
        Item {
            parent:resultsList;anchors.centerIn:parent;width:Math.max(0,resultsList.width-32)
            height:emptyLabel.implicitHeight+emptyReset.implicitHeight+10;visible:resultsList.count===0
            Text {id:emptyLabel;width:parent.width;horizontalAlignment:Text.AlignHCenter;wrapMode:Text.Wrap;text:launcher.pinnedOnly ? "No pinned apps match your search" : "No matching apps, windows or actions";color:Theme.muted;font.pixelSize:Theme.fontSize(12)}
            OrbitButton {id:emptyReset;objectName:"launcherClearFilters";anchors.top:emptyLabel.bottom;anchors.topMargin:10;anchors.horizontalCenter:parent.horizontalCenter;text:"Show all apps";quiet:true;onClicked:{launcher.pinnedOnly=false;search.text="";launcher.query="";launcher.focusSearch();}}
        }
    }
    RowLayout {
        visible: !launcher.showLayouts;Layout.fillWidth: true
        Text {text: launcher.results.length+" results";color: Theme.faint;font.pixelSize: Theme.fontSize(10);Layout.fillWidth: true}
        OrbitButton {objectName: "launcherShowDesktop";text: "Show desktop";quiet: true;implicitHeight: 24;onClicked: Orbit.showDesktop()}
        OrbitButton {objectName:"launcherHistoryOptions";text:"App history…";quiet:true;implicitHeight:24;onClicked:{launcher.historyOptions=!launcher.historyOptions;launcher.confirmHistoryReset=false;}}
    }
    Loader {id:layoutsLoader;opacity:launcher.viewOpacity;transform:Translate {y:launcher.viewOffset}
        Layout.fillWidth:true;Layout.fillHeight:true;visible:launcher.showLayouts;active:launcher.showLayouts;sourceComponent:Component{LayoutsPanel{}}}
    OrbitButton {Layout.fillWidth:true;text:"Undo "+Arrangements.undoLabel;visible:Arrangements.undoLabel!=="";enabled:!Arrangements.busy;quiet:true;onClicked:Arrangements.undo()}

}
