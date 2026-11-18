import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
import "SettingReveal.js" as SettingReveal
ColumnLayout {
    id: settings;objectName: "systemSettingsPanel"
    readonly property bool narrowNavigation: width < 620 + Math.max(0,Theme.textScale-1)*160
    readonly property int navigationWidth: Math.round(Math.min(184, width * .27))
    spacing: Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
    property int section: typeof Orbit.settingsSection!=="undefined" ? Orbit.settingsSection : 0
    readonly property var pageNames: ["input","lock","displays","shortcuts","accessibility","network","power-mode","battery","music","bluetooth","appearance","","help","","","brightness","tools"]
    readonly property string pageName: pageNames[Math.max(0,Math.min(pageNames.length-1,section))]
    // A stable viewport avoids feeding a child layout's implicit height back
    // into the window that is currently sizing that same child. Pages scroll.
    implicitHeight: 480
    property bool contentReady: false
    property string searchQuery: ""
    readonly property bool searching: !!searchQuery.trim()
    readonly property var searchResults: {
        var query=searchQuery.trim().toLowerCase();
        if(!query)return [];
        var tokens=query.split(/\s+/);
        var pages=settings.sections.map(function(entry){
            return {name:entry.label,description:entry.description || "",icon:entry.icon,
                    section:entry.value,words:[entry.label,entry.description || "",entry.keywords || ""].join(" ")};
        });
        var actions=typeof Orbit.systemActions==="undefined" ? [] : Orbit.systemActions || [];
        var controls=actions.filter(row => row.destination && row.destination.startsWith("setting:")).map(function(row){
            return {name:row.name,description:row.description,icon:row.icon,action:row.id,section:row.section,words:row.searchText};
        });
        function matches(row) {
            return tokens.every(token => (row.words || "").toLowerCase().indexOf(token)>=0);
        }
        var matchedControls=controls.filter(matches);
        var shortcutSections=matchedControls.map(row=>row.section);
        return pages.filter(row=>!shortcutSections.includes(row.section)).concat(matchedControls).map(function(row,ordinal){
            var name=row.name.toLowerCase();
            return {row:row, rank:!matches(row) ? -1 : name===query ? 0 : name.startsWith(query) ? 1
                    : tokens.every(token=>name.indexOf(token)>=0) ? 2 : 3, ordinal:ordinal};
        }).filter(match => match.rank>=0)
            .sort((a,b)=>a.rank-b.rank || a.ordinal-b.ordinal).map(match=>match.row);
    }
    function focusSearch() {
        search.forceActiveFocus(Qt.ShortcutFocusReason);
        search.selectAll();
    }
    function closeSearch() {
        search.clear();
    }
    function openSearchResult(row) {
        if(!row)return;
        closeSearch();
        if(row.action && typeof Orbit.activateSystemAction==="function")Orbit.activateSystemAction(row.action);
        else if(row.section!==undefined)selectSection(row.section);
        if(page.item)page.item.forceActiveFocus(Qt.TabFocusReason);
    }
    Shortcut {sequence: StandardKey.Find;onActivated:settings.focusSearch()}
    NumberAnimation {
        id:pageFade;objectName:"settingsPageFade";target:page;property:"opacity"
        from:0.76;to:1;duration:Theme.motionDuration(130,80);easing.type:Easing.OutCubic
    }
    readonly property bool motionDisabled:!Theme.panelMotionEnabled
    onMotionDisabledChanged:if(motionDisabled){pageFade.stop();page.opacity=1;}
    property string lastTargetSerial: ""
    function revealPending(attempt) {
        var request=typeof Orbit.settingsTarget!=="undefined" ? Orbit.settingsTarget : ({});
        if(!request.serial || request.serial===lastTargetSerial || request.section!==section || !page.item)return;
        if(typeof page.item.revealSetting==="function") {
            page.item.revealSetting(request.tab,request.target);lastTargetSerial=request.serial;return;
        }
        if(SettingReveal.reveal(page.item,request.target)){lastTargetSerial=request.serial;return;}
        if(attempt<4)Qt.callLater(function(){settings.revealPending(attempt+1);});
        else {page.item.forceActiveFocus(Qt.TabFocusReason);lastTargetSerial=request.serial;}
    }
    function queueReveal(){Qt.callLater(function(){settings.revealPending(0);});}
    property bool noticeQueued: false
    function notifyPage() {
        noticeQueued=false;
        if(typeof Orbit.settingsPageOpened==="function")Orbit.settingsPageOpened(pageName);
    }
    function queueNotice() {
        if(noticeQueued)return;
        noticeQueued=true;Qt.callLater(notifyPage);
    }
    // Send only local selections back to the host. Echoing an incoming update
    // can replay stale sections when several selections are in flight.
    function selectSection(value) {
        if(!pageNames[value])value=0;
        if(section===value)return;
        section=value;
        if(typeof Orbit.rememberSettingsSection==="function")Orbit.rememberSettingsSection(value);
    }
    onSectionChanged: {if(!pageNames[section])section=0;queueNotice();}
    Component.onCompleted: {contentReady=true;queueNotice();queueReveal();}
    Connections {
        target: Orbit
        function onInteractionChanged() {
            if(settings.section!==Orbit.settingsSection) {
                settings.closeSearch();
                settings.section=Orbit.settingsSection;
            }
            var target=typeof Orbit.settingsTarget!=="undefined" ? Orbit.settingsTarget : ({});
            if(target.serial && target.serial!==settings.lastTargetSerial)settings.closeSearch();
            settings.queueReveal();
        }
    }
    readonly property var sections: [
        {value:12,label:"Getting around",icon:"help-browser",group:"START",description:"Find actions and learn the everyday shortcuts"},
        {value:10,label:"Appearance",icon:"color-select",group:"DESKTOP",keywords:"theme accent colours colors dark light contrast taskbar wallpaper"},
        {value:2,label:"Displays",icon:"video-display",group:"DESKTOP",keywords:"resolution scale scaling monitor output orientation screen hdmi"},
        {value:15,label:"Brightness",icon:"display-brightness",group:"DESKTOP"},
        {value:5,label:"Network",icon:"network-wireless",group:"CONNECTIONS",keywords:"wi-fi wifi internet ethernet wireless connections"},
        {value:9,label:"Bluetooth",icon:"bluetooth-active",group:"CONNECTIONS",keywords:"pair device wireless headset"},
        {value:8,label:"Sound",icon:"audio-volume-high",group:"DEVICES",keywords:"speakers headphones audio output mixer playback volume profile"},
        {value:0,label:"Input",icon:"input-keyboard",group:"DEVICES",keywords:"keyboard layout mouse touchpad repeat scroll natural sensitivity"},
        {value:6,label:"Power mode",icon:"system-shutdown",group:"POWER"},
        {value:7,label:"Battery health",icon:"battery-good",group:"POWER"},
        {value:1,label:"Lock",icon:"system-lock-screen",group:"POWER",keywords:"screen lock sleep idle suspend display timeout"},
        {value:4,label:"Accessibility",icon:"preferences-desktop-accessibility",group:"ACCESS",keywords:"keyboard screen reader assistive input"},
        {value:3,label:"Shortcuts",icon:"preferences-desktop-keyboard-shortcuts",group:"ACCESS",keywords:"keyboard bindings hotkeys"},
        {value:16,label:"System tools",icon:"preferences-system",group:"SYSTEM"},
    ]
    DisplayConfirmation { Layout.fillWidth: true }
    OrbitField {
        id: search;objectName: "settingsSearchField"
        parent: settings.narrowNavigation ? compactSearchHost : sidebarSearchHost
        anchors.fill: parent
        implicitHeight: Math.max(32,Theme.labelSize+16)
        leftPadding: 8;rightPadding: 8;font.pixelSize: Theme.labelSize
        placeholderText:"Find a setting"
        accessibleLabel:"Find a setting (Ctrl+F)"
        maximumLength: 120
        onTextChanged: settings.searchQuery=text
        onAccepted: if(settings.searching)settings.openSearchResult(settings.searchResults[Math.max(0,results.currentIndex)]);
        Keys.onEscapePressed: event => {
            event.accepted=settings.searching;
            if(event.accepted)settings.closeSearch();
        }
        Keys.onDownPressed: event => {
            event.accepted=settings.searching && results.count>0;
            if(event.accepted){results.currentIndex=0;results.forceActiveFocus(Qt.TabFocusReason);}
        }
    }
    GridLayout {
        objectName: "settingsNavigationHeader"
        visible: settings.narrowNavigation
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        columns: width>=420 ? 2 : 1
        rowSpacing: settings.spacing;columnSpacing: settings.spacing
        Item {
            id: compactSearchHost
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: search.implicitHeight
        }
        SettingsChoice {
            id: pageChoice;objectName: "settingsPageChoice"
            visible: settings.narrowNavigation
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 180
            implicitHeight: search.implicitHeight
            font.pixelSize: Theme.labelSize
            textRole: "label"
            model: settings.sections
            currentIndex: settings.sections.findIndex(row => row.value === settings.section)
            Accessible.name: "Settings section"
            onActivated: idx => {settings.closeSearch();settings.selectSection(settings.sections[idx].value);}
        }
    }
    Item {
        id: settingsBody
        Layout.fillWidth: true;Layout.fillHeight: true
        Layout.minimumWidth: 0;Layout.minimumHeight: 0
        ColumnLayout {
            id: sidebar
            visible: !settings.narrowNavigation
            anchors.left: parent.left;anchors.top: parent.top;anchors.bottom: parent.bottom
            width: settings.navigationWidth
            spacing: settings.spacing
            Item {
                id: sidebarSearchHost
                Layout.fillWidth: true
                implicitHeight: search.implicitHeight
            }
            SectionIndex {
                id: index;objectName: "systemSettingsIndex"
                Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 0
                sections: settings.sections
                current: settings.section
                onSelected: value => {settings.closeSearch();settings.selectSection(value);}
            }
        }
        Item {
            objectName: "settingsContentViewport"
            anchors.top: parent.top;anchors.bottom: parent.bottom;anchors.right: parent.right
            anchors.left: settings.narrowNavigation ? parent.left : sidebar.right
            anchors.leftMargin: settings.narrowNavigation ? 0 : settings.spacing
            ColumnLayout {
                anchors.fill: parent
                visible: settings.searching
                spacing: 8
                Text {
                    Layout.fillWidth: true
                    text: "Search results"
                    color: Theme.text;font.pixelSize: Theme.headingSize;font.weight: Font.DemiBold
                }
                Text {
                    visible: !results.count
                    Layout.fillWidth: true;text: "No settings match. Try a shorter search."
                    color: Theme.muted;font.pixelSize: Theme.detailSize;wrapMode: Text.Wrap
                }
                ListView {
                    id: results;objectName: "settingsSearchResults"
                    Layout.fillWidth: true;Layout.fillHeight: true
                    model: settings.searchResults
                    onModelChanged: currentIndex=count ? 0 : -1
                    visible: count>0
                    clip: true;spacing: 4;activeFocusOnTab: true;keyNavigationEnabled: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}
                    Keys.onReturnPressed: settings.openSearchResult(settings.searchResults[currentIndex])
                    Keys.onEnterPressed: settings.openSearchResult(settings.searchResults[currentIndex])
                    Keys.onEscapePressed: {settings.closeSearch();settings.focusSearch();}
                    delegate: OrbitButton {
                        id: result
                        required property var modelData
                        required property int index
                        width: results.width;quiet: results.currentIndex!==index
                        implicitHeight: contentItem.implicitHeight+2*padding
                        Accessible.name: modelData.name
                        Accessible.description: modelData.description
                        onClicked: settings.openSearchResult(modelData)
                        contentItem: RowLayout {
                            spacing: 8
                            Image {
                                Layout.preferredWidth: 16;Layout.preferredHeight: 16
                                source: Theme.symbolicIconSource(result.modelData.icon)
                                sourceSize: Qt.size(16,16)
                            }
                            ColumnLayout {
                                Layout.fillWidth: true;Layout.minimumWidth: 0;spacing: 2
                                Text {
                                    Layout.fillWidth: true;text: result.modelData.name
                                    color: Theme.text;font.pixelSize: Theme.labelSize
                                    textFormat: Text.PlainText;elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true;text: result.modelData.description
                                    visible: !!text
                                    color: Theme.muted;font.pixelSize: Theme.detailSize
                                    textFormat: Text.PlainText;elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
            Loader {
                id: page;objectName: "settingsPageLoader";anchors.fill: parent
                visible: !settings.searching
                sourceComponent: [inputs,locks,displays,shortcuts,accessibility,network,power,battery,sound,bluetooth,appearance,null,help,null,null,brightness,systemTools][Math.max(0,Math.min(16,settings.section))]
                onLoaded: {
                    pageFade.stop();page.opacity=1;
                    if(settings.contentReady && Theme.panelMotionEnabled)pageFade.start();
                    settings.queueNotice();settings.queueReveal();
                }
            }
        }
    }
    Component {id: help;GettingAroundPanel {onSectionRequested: value => settings.selectSection(value)}}
    Component {id: inputs;InputPanel {}}
    Component {id: locks;LockPanel {}}
    Component {id: displays;DisplayPanel {}}
    Component {id: shortcuts;ShortcutsPanel {}}
    Component {id: accessibility;AccessibilityPanel {}}
    Component {id: network;NetworkPanel {}}
    Component {id: power;PowerPanel {}}
    Component {id: battery;ScrollView {
        id: batteryView;clip: true;contentWidth: availableWidth;implicitHeight: batteryContent.implicitHeight
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        BatteryPanel {id: batteryContent;width: batteryView.availableWidth}
    }}
    Component {id: sound;MusicPanel {showPlayback: false}}
    Component {id: bluetooth;BluetoothPanel {}}
    Component {id: appearance;AppearancePanel {}}
    Component {id: brightness;ScrollView {
        id: brightnessView;clip: true;contentWidth: availableWidth;implicitHeight: brightnessContent.implicitHeight
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        BrightnessPanel {id: brightnessContent;width: brightnessView.availableWidth}
    }}
    Component {id:systemTools;SystemToolsPanel {}}

}
