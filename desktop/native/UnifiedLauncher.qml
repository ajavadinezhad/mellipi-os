import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: launcher
    objectName: "unifiedLauncher"
    property bool compactViewport: false
    spacing: compactViewport ? 4 : Theme.sectionGap
    readonly property int toolbarHeight: Math.max(36, Theme.labelSize + 14)
    readonly property int actionHeight: Math.max(28, Theme.detailSize + 10)
    readonly property int controlGap: width < 360 ? 5 : 8
    readonly property bool labelDestinations: width >= Math.ceil(570*Theme.textScale)
    readonly property int resultGap: compactViewport ? 3 : Theme.extraCompact ? 4 : 6
    signal toolsRequested()
    property string query: ""
    property bool pinnedOnly: false
    property bool fileMode: false
    property string favoriteFolder: ""
    readonly property var fileSearch: typeof Orbit.launcherFiles==="undefined" ? null : Orbit.launcherFiles
    function changeSearchMode(files) {
        fileMode=files;pinnedOnly=false;historyOptions=false;
        if(fileSearch){
            fileSearch.cancel();
            if(files){
                fileSearch.refresh();
                const folders=fileSearch.folders || [];
                if(!folders.some(row=>row.path===favoriteFolder))
                    favoriteFolder=folders.length===1 ? folders[0].path : "";
                queueFileSearch();
            }
        }
        queueRebuild();focusSearch();
    }
    Keys.onEscapePressed: event => {
        event.accepted=launcher.fileMode || launcher.historyOptions;
        if(launcher.fileMode)launcher.changeSearchMode(false);
        else if(launcher.historyOptions){
            launcher.historyOptions=false;
            launcher.confirmHistoryReset=false;
            launcher.focusSearch();
        }
    }
    function queueFileSearch() {
        if(fileMode && fileSearch)fileSearch.search(favoriteFolder,query);
    }
    property bool historyOptions: false
    property bool confirmHistoryReset: false
    onPinnedOnlyChanged: queueRebuild()
    property var results: []
    property bool rebuildPending: false
    property bool rebuildNeeded: true
    property var catalog: null
    property var windowData: null
    property var actionsData: null
    property var pins: null
    onQueryChanged: {queueFileSearch();queueRebuild();}
    onVisibleChanged: {if(visible)queueRebuild();else if(fileMode && fileSearch)fileSearch.cancel();}
    function queueRebuild() {
        rebuildNeeded=true;
        if (!visible || rebuildPending) return;
        rebuildPending=true;
        Qt.callLater(function(){
            rebuildPending=false;
            flushRebuild();
        });
    }
    function flushRebuild() {
        if (!visible || !rebuildNeeded) return;
        rebuildNeeded=false;
        rebuild();
    }
    function resetForOpen() {
        if(fileMode)changeSearchMode(false);
        pinnedOnly=false;
        historyOptions=false;
        confirmHistoryReset=false;
        search.text="";
        query="";
        if(resultsList.count)resultsList.currentIndex=0;
        focusSearch();
    }
    function normalize(value) {return (value || "").trim().toLowerCase().replace(/\s+/g," ");}
    function compact(value) {return (value || "").toLowerCase().replace(/[\s_-]+/g,"");}
    function searchTerms(row) {
        return (row.searchText || [row.name,row.description,row.genericName || "",(row.keywords || []).join(" ")].join(" ")).toLowerCase();
    }
    function readSnapshot(section, fallback) {
        return typeof Orbit.launcherSearchSnapshot==="function"
            ? JSON.parse(Orbit.launcherSearchSnapshot(section)) : fallback();
    }
    function appData() {
        if(catalog) return catalog;
        var apps=readSnapshot("apps", function(){return Orbit.launcherApps;}), byId=Object.create(null);
        var entries=apps.map(function(app){
            var item={app:app, name:normalize(app.name), terms:searchTerms(app)};
            byId[app.id]=item;
            return item;
        });
        catalog={entries:entries, byId:byId};
        return catalog;
    }
    function currentWindows() {
        if(windowData)return windowData;
        var groupByWindow=Object.create(null), running=Object.create(null), settingsTask=null;
        var state=readSnapshot("windows", function(){
            return {windows:Orbit.windows,filter:Orbit.windowFilter || [],dock:Orbit.dockApps,desktops:Orbit.desktops};
        });
        var windows=state.windows, ids=state.filter, filter=Object.create(null);
        ids.forEach(function(id){filter[String(id)]=true;});
        state.dock.forEach(function(group){
            if(group.id==="orbit-settings")settingsTask=group;
            if(group.windows.length)running[group.id]=true;
            group.windows.forEach(function(window){groupByWindow[String(window.id)]=group;});
        });
        var active=state.desktops.find(function(space){return space.active;});
        var settingsOpen=windows.some(function(window){return isSettingsWindow(window.klass);});
        windowData={windows:windows, filter:filter, onlyWindows:ids.length>0,
            groupByWindow:groupByWindow,running:running,settingsTask:settingsTask,
            active:active,desktops:state.desktops,settingsOpen:settingsOpen};
        return windowData;
    }
    function isSettingsWindow(klass) {
        var lower=(klass || "").toLowerCase();
        return lower==="orbit-settings" || lower==="orbit-settings.desktop";
    }
    function systemActionData() {
        if(actionsData)return actionsData;
        var actions=readSnapshot("actions", function(){return Orbit.systemActions || [];});
        var loginTarget=actions.some(function(action){return action.id==="switch-user";}) ? "switch-user" : "session";
        actionsData={aliases:{login:loginTarget,signin:loginTarget,signout:"logout",logoff:"logout",poweroff:"shutdown",turnoff:"shutdown"},
            entries:actions.map(function(action){return {action:action, id:compact(action.id), name:compact(action.name),
                nameTerms:(action.name || "").toLowerCase(),terms:searchTerms(action)};})};
        return actionsData;
    }
    function rebuild() {
        if(fileMode){results=fileSearch ? fileSearch.rows : [];return;}
        // Read each QVariant list at most once per invalidation. Repeated reads
        // inside a match loop would marshal whole Python models into QML.
        var text=normalize(query), words=text ? text.split(" ") : [];
        var bestActions=[], bestNearby=[], bestElsewhere=[], bestApps=[], rows=[], nearby=[], elsewhere=[];
        var apps=appData(), snapshot=currentWindows(), windowOnly=snapshot.onlyWindows, settingsAction=false;
        var activeSpace=snapshot.active, running=snapshot.running;
        if(!pins){
            var set=Object.create(null);
            readSnapshot("pins", function(){return Orbit.appearance.pins || [];}).forEach(function(id){set[id]=true;});
            pins=set;
        }
        function matches(haystack){
            for(var i=0;i<words.length;i++)if(haystack.indexOf(words[i])<0)return false;
            return true;
        }
        function add(row,group,bestMatches,exact) {
            if(exact)row.category="Best matches";
            (exact ? bestMatches : group).push(row);
        }
        if(text && !pinnedOnly && !windowOnly) {
            var actions=systemActionData(), normalized=compact(text), actionRows=[];
            actions.entries.forEach(function(item,index){
                var exact=normalized===item.id || normalized===item.name || actions.aliases[normalized]===item.action.id;
                if(exact || matches(item.terms))actionRows.push({action:item.action,rank:exact ? 0 : matches(item.nameTerms) ? 1 : 2,index:index});
            });
            actionRows.sort(function(a,b){return a.rank-b.rank || a.index-b.index;}).forEach(function(item){
                var action=item.action;
                if(action.id==="settings")settingsAction=true;
                add({kind:"action",id:action.id,appId:"",name:action.name,description:action.description,icon:action.icon,category:"System actions"},rows,bestActions,item.rank===0);
            });
        }
        snapshot.windows.forEach(function(window){
            if(settingsAction && isSettingsWindow(window.klass))return;
            var id=String(window.id);
            if(windowOnly && !snapshot.filter[id])return;
            var group=snapshot.groupByWindow[id];
            if(!windowOnly && pinnedOnly && (!group || !pins[group.id]))return;
            var name=group ? group.name : window.klass || "Application";
            var metadata=group && apps.byId[group.id];
            var space=snapshot.desktops.find(function(item){return item.id===window.desktop;});
            var spaceLabel=window.desktop<0 ? "All workspaces" : space && space.name && !/^\d+$/.test(space.name) ? space.name : "Workspace "+(window.desktop+1);
            if(!matches((name+" "+window.title+" "+spaceLabel).toLowerCase()+" "+(metadata ? metadata.terms : "")))return;
            var here=window.desktop<0 || (activeSpace && window.desktop===activeSpace.id);
            var exact=!!text && (normalize(window.title)===text || normalize(group ? group.name : window.klass)===text);
            add({kind:"window",id:id,appId:group ? group.id : "",name:window.title || name,description:name+" · "+(window.minimized ? "Minimized · " : "")+spaceLabel,icon:window.icon || "application-x-executable",category:here ? "This workspace" : "Other workspaces"},here ? nearby : elsewhere,here ? bestNearby : bestElsewhere,exact);
        });
        var task=snapshot.settingsTask;
        if(task && !windowOnly && !settingsAction && !snapshot.settingsOpen && !pinnedOnly && matches((task.name+" settings preferences").toLowerCase()))
            nearby.push({kind:"task",id:task.id,appId:"",name:task.name,description:"Return to settings",icon:task.icon,category:"This workspace"});
        rows=rows.concat(nearby,elsewhere);
        if(!windowOnly)apps.entries.forEach(function(entry){
            var app=entry.app;
            if(app.id==="orbit-settings.desktop" && (settingsAction || snapshot.settingsOpen))return;
            var exact=!!text && entry.name===text;
            if((pinnedOnly && !pins[app.id]) || (running[app.id] && !exact) || !matches(entry.terms))return;
            add({kind:"app",id:app.id,appId:app.id,name:app.name,description:running[app.id] ? "Launch app again" : app.description || "Launch application",icon:app.icon,category:"Applications"},rows,bestApps,exact);
        });
        // Enter opens the first row: keep explicit action names and aliases ahead of exact app and window matches.
        rows=bestActions.concat(bestNearby,bestElsewhere,bestApps,rows);
        if (text && !windowOnly && !pinnedOnly && (/^=/.test(text) || /[0-9].*[+*\/^%×÷−-]|[+*\/^%×÷−-].*[0-9]/.test(text))) {
            var answer=Orbit.launcherCalculation(query);
            if (answer) rows.unshift({kind:"calculation",id:answer,appId:"",name:answer,
                description:"Copy result",icon:"calculator",category:"Calculator"});
        }
        var previous=results;
        if(rows.length!==previous.length || rows.some(function(row,i){
            var old=previous[i];
            return row.kind!==old.kind || row.id!==old.id || row.appId!==old.appId ||
                   row.name!==old.name || row.description!==old.description ||
                   row.icon!==old.icon || row.category!==old.category;
        }))results=rows;
    }
    function activateFromKeyboard(row, event) {
        if (row && (event.modifiers & Qt.ControlModifier) && (row.kind==="app" || row.kind==="task")) {
            Orbit.launchAnother(row.id);event.accepted=true;
        } else {
            activate(row);event.accepted=true;
        }
    }
    function activate(row){if(!row)return;if(row.kind==="calculation")Orbit.copyCalculation(row.id);else if(row.kind==="action")Orbit.activateSystemAction(row.id);else if(row.kind==="task")Orbit.activateDock(row.id,false);else if(row.kind==="window")Orbit.focusWindow(row.id);else if(row.kind==="file" && fileSearch)fileSearch.open(row.id);else Orbit.launch(row.id);}
    function openResultMenu(index) {
        var row=results[index];if(!row || row.kind==="action" || row.kind==="calculation" || row.kind==="file")return false;
        var item=resultsList.itemAtIndex(index);if(!item)return false;
        Orbit.openPanelContext(item,row.kind==="task" ? "app" : row.kind,row.id,item.width/2,item.height/2);return true;
    }
    function focusSearch(){if(search.visible && search.enabled)search.forceActiveFocus(Qt.ShortcutFocusReason); }
    Component.onCompleted: {queueRebuild();Qt.callLater(focusSearch);}
    Connections {
        target: Orbit;ignoreUnknownSignals: true
        function onWindowsChanged(){launcher.windowData=null;launcher.queueRebuild();}
        function onLauncherChanged(){launcher.catalog=null;launcher.windowData=null;launcher.queueRebuild();}
        function onSettingsChanged(){launcher.pins=null;launcher.queueRebuild();}
        function onSystemActionsChanged(){launcher.actionsData=null;launcher.queueRebuild();}
    }
    Connections {
        target:launcher.fileSearch
        function onChanged(){if(launcher.fileMode)launcher.queueRebuild();}
    }
    RowLayout {
        Layout.fillWidth:true;visible:launcher.fileMode
        SettingsChoice {
            objectName:"launcherFavoriteFolder";Layout.fillWidth:true;Layout.minimumWidth:0
            Accessible.name:"Favorite folder to search";textRole:"label"
            model:[{path:"",label:"Choose a favorite folder"},...(launcher.fileSearch ? launcher.fileSearch.folders : [])]
            currentIndex:Math.max(0,model.findIndex(row=>row.path===launcher.favoriteFolder))
            onActivated:index=>{launcher.favoriteFolder=model[index].path;launcher.queueFileSearch();launcher.focusSearch();}
        }
    }
    GridLayout {
        id: searchTools
        Layout.fillWidth: true
        readonly property bool showAppOptions: !launcher.fileMode && !(Orbit.windowFilter && Orbit.windowFilter.length)
        readonly property bool inlineOptions: width >= Math.ceil(365 * Theme.textScale)
        columns: showAppOptions ? (launcher.fileSearch && inlineOptions ? 4 : 3) : launcher.fileSearch ? 2 : 1
        columnSpacing: launcher.controlGap
        rowSpacing: launcher.resultGap
        OrbitField {
            id: search;objectName: "foldAppSearch"
            Layout.columnSpan: searchTools.showAppOptions && !searchTools.inlineOptions ? (launcher.fileSearch ? 2 : 3) : 1
            Layout.fillWidth: true;Layout.minimumWidth: 0;implicitHeight: launcher.toolbarHeight
            placeholderText: launcher.fileMode ? "Search favorite folder…" : width < Math.ceil(235 * Theme.textScale) ? "Search…" : "Search apps, windows, actions…"
            accessibleLabel: launcher.fileMode ? "Search favorite folder" : "Search apps, windows, and actions";font.pixelSize: Theme.labelSize
            leftPadding: 34;rightPadding: 10
            Image {
                anchors.left: parent.left;anchors.leftMargin: 10;anchors.verticalCenter: parent.verticalCenter
                width: 17;height: 17;sourceSize: Qt.size(24,24)
                source: Theme.symbolicIconSource("start-search", Theme.accentInk)
            }
            onTextChanged: launcher.query=text
            Keys.onReturnPressed: event => {
                if (!(event.modifiers & Qt.ControlModifier)) {event.accepted=false;return;}
                launcher.flushRebuild();
                if (launcher.results.length)
                    launcher.activateFromKeyboard(launcher.results[0],event);
            }
            onAccepted: {launcher.flushRebuild(); if(launcher.results.length)launcher.activate(launcher.results[0]);}
            Keys.onDownPressed: {launcher.flushRebuild(); if(resultsList.count){resultsList.currentIndex=0;resultsList.forceActiveFocus();}}
        }
        IconButton {
            objectName:"launcherFileMode";visible:!!launcher.fileSearch;iconName:"start-search"
            text:""
            accent:launcher.fileMode;hint:launcher.fileMode ? "Back to apps and actions" : "Find files in a favorite folder"
            implicitWidth:Math.max(launcher.actionHeight,contentItem.implicitWidth+2*padding)
            implicitHeight:launcher.actionHeight
            onClicked:launcher.changeSearchMode(!launcher.fileMode)
        }
        SettingsChoice {
            objectName: "launcherSortOptions"
            visible: searchTools.showAppOptions
            Layout.fillWidth: !searchTools.inlineOptions
            Layout.preferredWidth: Math.ceil(124 * Theme.textScale)
            Layout.minimumWidth: 0
            implicitHeight: launcher.toolbarHeight
            Accessible.name: "Sort applications"
            textRole: "label"
            model: [{label:"Most used",value:"frequent"},{label:"Recent",value:"recent"},{label:"A–Z",value:"name"}]
            currentIndex: model.findIndex(row => row.value === (Orbit.appearance.launcherSort || "frequent"))
            onActivated: index => Orbit.setPreference("launcherSort",model[index].value)
        }
        RowLayout {
            visible: searchTools.showAppOptions
            // On narrow layouts the app filters share one row with sorting.
            Layout.columnSpan: searchTools.inlineOptions ? 1 : 2
            spacing: launcher.controlGap
            IconButton {
                objectName: "launcherPinnedFilter"
                iconName: launcher.pinnedOnly ? "pinned" : "pin"
                accent: launcher.pinnedOnly
                implicitWidth: launcher.actionHeight;implicitHeight: launcher.actionHeight
                hint: launcher.pinnedOnly ? "Show all apps and windows" : "Show pinned apps and their open windows"
                onClicked: launcher.pinnedOnly=!launcher.pinnedOnly
            }
            IconButton {
                objectName:"launcherHistoryOptions";iconName:"history"
                hint:launcher.historyOptions ? "Hide app usage options" : "App usage options"
                accent:launcher.historyOptions
                implicitWidth:launcher.actionHeight;implicitHeight:launcher.actionHeight
                onClicked:{launcher.historyOptions=!launcher.historyOptions;launcher.confirmHistoryReset=false;}
            }
        }
    }
    GridLayout {
        id: historyControls
        visible:searchTools.visible && searchTools.showAppOptions && launcher.historyOptions;Layout.fillWidth:true
        columns: historyLabel.implicitWidth + resetHistory.implicitWidth + closeHistory.implicitWidth
                 + 2*columnSpacing <= width ? 3 : 2
        columnSpacing: launcher.controlGap
        rowSpacing: launcher.resultGap
        Text {
            id: historyLabel
            Layout.fillWidth:true;Layout.minimumWidth:0;Layout.columnSpan: historyControls.columns===2 ? 2 : 1
            text:launcher.confirmHistoryReset ? "Clear app counts and recent ordering?" : "Application usage is stored locally."
            wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.detailSize
        }
        OrbitButton {id: resetHistory;objectName:"launcherResetUsage";Layout.fillWidth: historyControls.columns===2;Layout.minimumWidth: 0;text:launcher.confirmHistoryReset ? "Clear history" : "Clear history…";implicitHeight:launcher.actionHeight;onClicked:{if(launcher.confirmHistoryReset){Orbit.clearLauncherHistory();launcher.confirmHistoryReset=false;launcher.historyOptions=false;}else launcher.confirmHistoryReset=true;}}
        IconButton {id: closeHistory;iconName:"close";hint:"Cancel";implicitWidth:launcher.actionHeight;implicitHeight:launcher.actionHeight;onClicked:{launcher.historyOptions=false;launcher.confirmHistoryReset=false;}}
    }
    ListView {
        id: resultsList;objectName: "unifiedResults";Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 0
        model: launcher.results;clip: true;cacheBuffer: 0;reuseItems: true;spacing: launcher.resultGap
        boundsBehavior: Flickable.StopAtBounds;activeFocusOnTab: true;keyNavigationEnabled: true
        section.property: launcher.compactViewport ? "" : "category";section.criteria: ViewSection.FullString
        section.delegate: Item {
            width: resultsList.width
            height: Math.max(30, heading.implicitHeight + 12)
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 12
                Rectangle {
                    implicitWidth: 10
                    implicitHeight: 2
                    radius: 1
                    color: Theme.accentInk
                }
                Text {
                    id: heading
                    text: section
                    color: Theme.text
                    font.pixelSize: Theme.detailSize
                    font.weight: Font.DemiBold
                }
                Item { Layout.fillWidth: true }
            }
        }
        onCountChanged: currentIndex=count ? Math.max(0,Math.min(currentIndex,count-1)) : -1
        Keys.onPressed:event=>{if(event.key===Qt.Key_Menu || (event.key===Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))){event.accepted=launcher.openResultMenu(currentIndex);}}
        Keys.onReturnPressed: event => launcher.activateFromKeyboard(launcher.results[currentIndex],event)
        Keys.onEnterPressed: event => launcher.activateFromKeyboard(launcher.results[currentIndex],event)
        Keys.onSpacePressed: launcher.activate(launcher.results[currentIndex])
        Keys.onUpPressed: {if(currentIndex<=0){search.forceActiveFocus();event.accepted=true;}else event.accepted=false;}
        delegate: Rectangle {
            id: result;objectName: "unifiedResult";required property var modelData;required property int index
            readonly property int rowInset: launcher.compactViewport ? 3 : Theme.extraCompact ? 6 : Theme.compact ? 9 : 12
            width: resultsList.width
            height: Math.max(launcher.compactViewport ? 38 : Theme.extraCompact ? 44 : Theme.compact ? 56 : 64, Math.ceil(resultContent.implicitHeight)+2*rowInset)
            radius: Theme.corner(5)
            color: resultsList.currentIndex===index ? Theme.selectedSurface : hit.containsMouse ? Theme.hover : "transparent"
            border.color: Theme.focusColor
            border.width: resultsList.activeFocus && resultsList.currentIndex===index ? 1 : 0
            onActiveFocusChanged:if(activeFocus)resultsList.currentIndex=index
            Accessible.role: Accessible.Button;Accessible.name: modelData.name;Accessible.description: modelData.description
            Accessible.onPressAction: launcher.activate(modelData)
            MouseArea {
                id: hit;anchors.fill: parent;hoverEnabled: true;acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: mouse => {resultsList.currentIndex=index;if(mouse.button===Qt.RightButton){if(modelData.kind!=="action" && modelData.kind!=="calculation" && modelData.kind!=="file")Orbit.openPanelContext(hit,modelData.kind==="task" ? "app" : modelData.kind,modelData.id,mouse.x,mouse.y);}else launcher.activate(modelData);}
            }
            RowLayout {
                id: resultContent;anchors.fill: parent;anchors.margins: result.rowInset;spacing: launcher.width < 360 ? 5 : Theme.extraCompact ? 7 : 10
                Rectangle {
                    readonly property string icon: modelData.icon || "application-x-executable"
                    readonly property bool systemGlyph: modelData.kind==="action" ||
                        modelData.kind==="calculation" || icon.indexOf("mellipi-")===0
                    readonly property color ink: Theme.legibleInk(Theme.accent,4.5,[Theme.luminance(color)])
                    Layout.preferredWidth: 32
                    Layout.preferredHeight: 32
                    radius: Theme.corner(8)
                    color: Theme.highContrast ? Theme.raised :
                        Qt.tint(result.color.a>0 ? result.color : Theme.surface,
                                Qt.rgba(Theme.accent.r,Theme.accent.g,Theme.accent.b,.14))
                    border.width: Theme.highContrast ? 1 : 0
                    border.color: Theme.controlBorder
                    Image {
                        anchors.centerIn: parent
                        width: parent.systemGlyph ? 20 : 23
                        height: width
                        source: parent.systemGlyph ? Theme.symbolicIconSource(
                            modelData.kind==="calculation" ? "start-calculate" : parent.icon, parent.ink)
                            : Theme.iconSource(parent.icon)
                        sourceSize: Qt.size(32,32)
                        fillMode: Image.PreserveAspectFit
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true;Layout.minimumWidth: 0;spacing: 3
                    Text {objectName: modelData.kind==="calculation" ? "launcherCalculationResult" : "";text: modelData.name;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.text;font.pixelSize: Theme.labelSize;textFormat: Text.PlainText}
                    Text {visible: !launcher.compactViewport;text: modelData.description;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.muted;font.pixelSize: Theme.detailSize;textFormat: Text.PlainText}
                }
                IconButton {
                    objectName: "unifiedWindowActions"
                    visible: ["window","app","task"].includes(modelData.kind)
                    opacity: resultsList.currentIndex===result.index || hit.containsMouse || activeFocus ? 1 : 0
                    focusPolicy: Qt.ClickFocus
                    iconName: "more";hint: "Result actions"
                    accessibleLabel: hint+" · "+modelData.name
                    implicitWidth: 26;implicitHeight: 26
                    onActiveFocusChanged: if(activeFocus)resultsList.currentIndex=result.index
                    onClicked: launcher.openResultMenu(result.index)
                }
            }
        }
        Item {
            parent:resultsList;anchors.centerIn:parent;width:Math.max(0,resultsList.width-32)
            height:emptyLabel.implicitHeight+emptyReset.implicitHeight+10;visible:resultsList.count===0
            Text {id:emptyLabel;width:parent.width;horizontalAlignment:Text.AlignHCenter;wrapMode:Text.Wrap;text:launcher.fileMode ? (launcher.fileSearch.note || (launcher.favoriteFolder ? "No matching files" : "Choose a folder bookmarked in Files")) : launcher.pinnedOnly ? "No pinned apps match your search" : "No matching apps, windows or actions";color:Theme.muted;font.pixelSize:Theme.fontSize(12)}
            IconButton {id:emptyReset;objectName:"launcherClearFilters";visible:!launcher.fileMode;anchors.top:emptyLabel.bottom;anchors.topMargin:10;anchors.horizontalCenter:parent.horizontalCenter;iconName:"start-library";hint:"Show all apps";implicitWidth:launcher.actionHeight;implicitHeight:launcher.actionHeight;onClicked:{launcher.pinnedOnly=false;search.text="";launcher.query="";launcher.focusSearch();}}
        }
    }
    RowLayout {
        id: launcherFooter
        objectName: "launcherFooter"
        Layout.fillWidth: true;spacing: launcher.controlGap
        Text {
            text: launcher.results.length+" results";color: Theme.faint;font.pixelSize: Theme.detailSize
            Layout.fillWidth: true;Layout.minimumWidth: 0;elide: Text.ElideRight
        }
        IconButton {
            objectName: "foldToolsButton";iconName: "start-tools"
            text: launcher.labelDestinations ? "Files & notes" : ""
            hint: "Files & notes";accessibleLabel: "Open files and notes"
            implicitWidth: Math.max(launcher.actionHeight, contentItem.implicitWidth+2*padding)
            implicitHeight: launcher.actionHeight;onClicked: launcher.toolsRequested()
        }
    }

}
