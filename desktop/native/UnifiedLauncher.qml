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
    readonly property int previewWidth: Math.ceil(124 * Theme.textScale)
    // Optional previews yield to search results when height or width is scarce.
    readonly property int previewCount: Math.min(3, Math.floor((width+controlGap)/(previewWidth+controlGap)))
    signal toolsRequested()
    property string query: ""
    property bool showLayouts: false
    property bool pinnedOnly: false
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
    onQueryChanged: queueRebuild()
    onVisibleChanged: if(visible)queueRebuild()
    function queueRebuild() {
        rebuildNeeded=true;
        if (!visible || showLayouts || rebuildPending) return;
        rebuildPending=true;
        Qt.callLater(function(){
            rebuildPending=false;
            flushRebuild();
        });
    }
    function flushRebuild() {
        if (!visible || showLayouts || !rebuildNeeded) return;
        rebuildNeeded=false;
        rebuild();
    }
    function resetForOpen() {
        pinnedOnly=false;
        historyOptions=false;
        confirmHistoryReset=false;
        search.text="";
        query="";
        showLayouts=false;
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
            active:active,settingsOpen:settingsOpen};
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
    property bool viewReady: false
    property real viewOpacity: 1
    property real viewOffset: 0
    function settleView() {viewEnter.stop();viewOpacity=1;viewOffset=0;}
    onShowLayoutsChanged: {
        settleView();
        if(viewReady && !Theme.reducedMotion)viewEnter.restart();
        if(showLayouts) layoutsLoader.forceActiveFocus(); else {queueRebuild(); Qt.callLater(focusSearch);}
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
            if(!matches((name+" "+window.title).toLowerCase()+" "+(metadata ? metadata.terms : "")))return;
            var here=window.desktop<0 || (activeSpace && window.desktop===activeSpace.id);
            var spaceLabel=window.desktop<0 ? "All workspaces" : "Workspace "+(window.desktop+1);
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
    function activate(row){if(!row)return;if(showLayouts)return;if(row.kind==="calculation")Orbit.copyCalculation(row.id);else if(row.kind==="action")Orbit.activateSystemAction(row.id);else if(row.kind==="task")Orbit.activateDock(row.id,false);else if(row.kind==="window")Orbit.focusWindow(row.id);else Orbit.launch(row.id);}
    function openResultMenu(index) {
        var row=results[index];if(!row || row.kind==="action" || row.kind==="calculation")return false;
        var item=resultsList.itemAtIndex(index);if(!item)return false;
        Orbit.openPanelContext(item,row.kind==="task" ? "app" : row.kind,row.id,item.width/2,item.height/2);return true;
    }
    function focusSearch(){if(search.visible && search.enabled)search.forceActiveFocus(Qt.ShortcutFocusReason); }
    Component.onCompleted: {viewReady=true;queueRebuild();Qt.callLater(focusSearch);}
    Connections {
        target: Orbit;ignoreUnknownSignals: true
        function onWindowsChanged(){launcher.windowData=null;launcher.queueRebuild();}
        function onLauncherChanged(){launcher.catalog=null;launcher.windowData=null;launcher.queueRebuild();}
        function onSettingsChanged(){launcher.pins=null;launcher.queueRebuild();}
        function onSystemActionsChanged(){launcher.actionsData=null;launcher.queueRebuild();}
    }
    RowLayout {
        visible: launcher.showLayouts;Layout.fillWidth: true;spacing: launcher.controlGap
        IconButton {
            objectName: "foldLayoutsBack";iconName: "go-previous";text: "Apps & windows";hint: "Back to apps and windows"
            implicitHeight: launcher.toolbarHeight
            onClicked: {launcher.showLayouts=false;Qt.callLater(launcher.focusSearch);}
        }
        Item {Layout.fillWidth: true;Layout.minimumWidth: 0}
        IconButton {iconName: "start-tools";hint: "Files & notes";accessibleLabel: "Open files and notes";onClicked: launcher.toolsRequested()}
    }
    OrbitField {
        visible: !launcher.showLayouts;id: search;objectName: "foldAppSearch";Layout.fillWidth: true;Layout.minimumWidth: 0;implicitHeight: launcher.toolbarHeight
        placeholderText: "Search apps, windows, actions…";font.pixelSize: Theme.labelSize
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
            if (!launcher.showLayouts && launcher.results.length)
                launcher.activateFromKeyboard(launcher.results[0],event);
        }
        onAccepted: {launcher.flushRebuild(); if(!launcher.showLayouts && launcher.results.length)launcher.activate(launcher.results[0]);}
        Keys.onDownPressed: {launcher.flushRebuild(); if(!launcher.showLayouts && resultsList.count){resultsList.currentIndex=0;resultsList.forceActiveFocus();}}
    }
    RowLayout {
        visible:!launcher.showLayouts && !(Orbit.windowFilter && Orbit.windowFilter.length)
        Layout.fillWidth: true;spacing: launcher.controlGap
        IconButton {
            objectName: "launcherPinnedFilter"
            iconName: launcher.pinnedOnly ? "pinned" : "pin"
            accent: launcher.pinnedOnly
            implicitWidth: launcher.actionHeight
            implicitHeight: launcher.actionHeight
            hint: launcher.pinnedOnly ? "Show all apps and windows" : "Show pinned apps and their open windows"
            onClicked: launcher.pinnedOnly=!launcher.pinnedOnly
        }
        SettingsSegments {
            objectName: "launcherSortOptions"
            Layout.maximumWidth: implicitWidth
            value: Orbit.appearance.launcherSort || "frequent"
            segmentWidth: 76
            options: [{label:"Most used",value:"frequent"},{label:"Recent",value:"recent"},{label:"A–Z",value:"name"}]
            onSelected: value => Orbit.setPreference("launcherSort",value)
        }
        Item {Layout.fillWidth: true}
    }
    ColumnLayout {
        id: savedSpaces
        objectName: "launcherSavedSpaces"
        visible: !launcher.compactViewport && !launcher.showLayouts && !launcher.query.trim() && !launcher.pinnedOnly
                 && !(Orbit.windowFilter && Orbit.windowFilter.length) && Arrangements.layouts.length > 0
                 && launcher.previewCount > 0 && launcher.height >= (launcher.toolbarHeight + launcher.actionHeight + 250)
        Layout.fillWidth: true
        spacing: Theme.rowGap
        Text {
            text: "Pick up where you left off"
            color: Theme.text
            font.pixelSize: Theme.headingSize
            font.weight: Font.DemiBold
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: launcher.controlGap
            Repeater {
                model: savedSpaces.visible ? Arrangements.layouts.slice(0,launcher.previewCount) : []
                delegate: OrbitButton {
                    id: card
                    required property var modelData
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: Math.floor((savedSpaces.width - (launcher.previewCount-1)*launcher.controlGap)
                                                       / Math.max(1,launcher.previewCount))
                    implicitHeight: Math.max(86, Theme.labelSize + 62)
                    enabled: !Arrangements.busy
                    Accessible.name: "Resume " + modelData.name
                    hint: modelData.count + (modelData.count === 1 ? " window" : " windows")
                    onClicked: {
                        launcher.showLayouts = true;
                        Arrangements.resumeSaved(modelData.id);
                    }
                    contentItem: ColumnLayout {
                        spacing: Theme.smallGap
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: Theme.corner(5)
                            color: Theme.background
                            clip: true
                            Repeater {
                                model: card.modelData.tiles
                                delegate: Rectangle {
                                    required property var modelData
                                    x: modelData.x * parent.width
                                    y: modelData.y * parent.height
                                    width: Math.max(1, modelData.w * parent.width - 2)
                                    height: Math.max(1, modelData.h * parent.height - 2)
                                    color: Theme.selectedSurface
                                    radius: Theme.corner(3)
                                    Image {
                                        visible: parent.width >= 18 && parent.height >= 18
                                        anchors.centerIn: parent
                                        width: 16; height: 16
                                        source: visible ? Theme.iconSource(modelData.icon) : ""
                                        sourceSize: Qt.size(24,24)
                                        fillMode: Image.PreserveAspectFit
                                    }
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: card.modelData.name
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            font.pixelSize: Theme.labelSize
                            color: Theme.text
                        }
                    }
                }
            }
            Item {Layout.fillWidth: true;Layout.minimumWidth: 0;visible: Arrangements.layouts.length < launcher.previewCount}
        }
    }
    ListView {
        visible:!launcher.showLayouts
        opacity:launcher.viewOpacity;transform:Translate {y:launcher.viewOffset}
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
                onClicked: mouse => {resultsList.currentIndex=index;if(mouse.button===Qt.RightButton){if(modelData.kind!=="action" && modelData.kind!=="calculation")Orbit.openPanelContext(hit,modelData.kind==="task" ? "app" : modelData.kind,modelData.id,mouse.x,mouse.y);}else launcher.activate(modelData);}
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
                    visible: modelData.kind==="window"
                    iconName: "more";hint: "Window actions"
                    accessibleLabel: hint+" · "+modelData.name
                    implicitWidth: 26;implicitHeight: 26
                    onActiveFocusChanged: if(activeFocus)resultsList.currentIndex=result.index
                    onClicked: launcher.openResultMenu(result.index)
                }
                IconButton {objectName: "unifiedPin";onActiveFocusChanged:if(activeFocus)resultsList.currentIndex=result.index;visible: !!modelData.appId;iconName: launcher.pins && launcher.pins[modelData.appId] ? "pinned" : "pin";hint: launcher.pins && launcher.pins[modelData.appId] ? "Unpin app" : "Pin app";accessibleLabel: hint+" · "+modelData.name;implicitWidth: 26;implicitHeight: 26;onClicked: Orbit.togglePin(modelData.appId)}
            }
        }
        Item {
            parent:resultsList;anchors.centerIn:parent;width:Math.max(0,resultsList.width-32)
            height:emptyLabel.implicitHeight+emptyReset.implicitHeight+10;visible:resultsList.count===0
            Text {id:emptyLabel;width:parent.width;horizontalAlignment:Text.AlignHCenter;wrapMode:Text.Wrap;text:launcher.pinnedOnly ? "No pinned apps match your search" : "No matching apps, windows or actions";color:Theme.muted;font.pixelSize:Theme.fontSize(12)}
            IconButton {id:emptyReset;objectName:"launcherClearFilters";anchors.top:emptyLabel.bottom;anchors.topMargin:10;anchors.horizontalCenter:parent.horizontalCenter;iconName:"start-library";hint:"Show all apps";implicitWidth:launcher.actionHeight;implicitHeight:launcher.actionHeight;onClicked:{launcher.pinnedOnly=false;search.text="";launcher.query="";launcher.focusSearch();}}
        }
    }
    GridLayout {
        id: historyControls
        visible:!launcher.showLayouts && launcher.historyOptions;Layout.fillWidth:true
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
    RowLayout {
        id: launcherFooter
        objectName: "launcherFooter"
        visible: !launcher.showLayouts;Layout.fillWidth: true;spacing: launcher.controlGap
        Text {
            text: launcher.results.length+" results";color: Theme.faint;font.pixelSize: Theme.detailSize
            Layout.fillWidth: true;Layout.minimumWidth: 0;elide: Text.ElideRight
        }
        IconButton {
            objectName: "foldLayoutsButton";iconName: "start-spaces"
            text: launcher.labelDestinations ? "Layouts" : ""
            hint: "Saved layouts";accessibleLabel: "Open saved layouts";enabled: Arrangements.available
            implicitHeight: launcher.actionHeight;onClicked: launcher.showLayouts=true
        }
        IconButton {
            objectName: "foldToolsButton";iconName: "start-tools"
            text: launcher.labelDestinations ? "Files & notes" : ""
            hint: "Files & notes";accessibleLabel: "Open files and notes"
            implicitHeight: launcher.actionHeight;onClicked: launcher.toolsRequested()
        }
        Rectangle {width: 1;height: Theme.detailSize;color: Theme.separator;Layout.alignment: Qt.AlignVCenter}
        IconButton {objectName: "launcherShowDesktop";iconName: "display";hint: "Show desktop";implicitWidth: launcher.actionHeight;implicitHeight: launcher.actionHeight;onClicked: Orbit.showDesktop()}
        IconButton {objectName:"launcherHistoryOptions";iconName:"history";hint:launcher.historyOptions ? "Hide app usage options" : "App usage options";accent:launcher.historyOptions;implicitWidth:launcher.actionHeight;implicitHeight:launcher.actionHeight;onClicked:{launcher.historyOptions=!launcher.historyOptions;launcher.confirmHistoryReset=false;}}
        IconButton {
            objectName:"launcherUndoArrangement";iconName:"undo";hint:"Undo "+Arrangements.undoLabel
            implicitWidth:launcher.actionHeight;implicitHeight:launcher.actionHeight
            visible:Arrangements.undoLabel!=="";enabled:!Arrangements.busy
            onClicked:Arrangements.undo()
        }
    }
    Loader {id:layoutsLoader;opacity:launcher.viewOpacity;transform:Translate {y:launcher.viewOffset}
        Layout.fillWidth:true;Layout.fillHeight:true;visible:launcher.showLayouts;active:launcher.showLayouts;sourceComponent:Component{LayoutsPanel{}}}
}
