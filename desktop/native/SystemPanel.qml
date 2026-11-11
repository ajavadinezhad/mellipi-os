import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
import "SettingReveal.js" as SettingReveal
RowLayout {
    id: settings;objectName: "systemSettingsPanel";spacing: 12
    property int section: typeof Orbit.settingsSection!=="undefined" ? Orbit.settingsSection : 0
    readonly property var pageNames: ["input","lock","displays","shortcuts","accessibility","network","power-mode","battery","music","bluetooth","appearance","","help","","","brightness","tools"]
    readonly property string pageName: pageNames[Math.max(0,Math.min(pageNames.length-1,section))]
    // A stable viewport avoids feeding a child layout's implicit height back
    // into the window that is currently sizing that same child. Pages scroll.
    implicitHeight: 480
    property bool contentReady: false
    NumberAnimation {
        id:pageFade;objectName:"settingsPageFade";target:page;property:"opacity"
        from:0.76;to:1;duration:Theme.economy ? 80 : 130;easing.type:Easing.OutCubic
    }
    readonly property bool motionDisabled:Theme.reducedMotion
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
    onSectionChanged: {if(!pageNames[section])section=0;if(typeof Orbit.rememberSettingsSection==="function")Orbit.rememberSettingsSection(section);queueNotice();}
    Component.onCompleted: {contentReady=true;queueNotice();queueReveal();}
    Connections {
        target: Orbit
        function onInteractionChanged() {
            if(settings.section!==Orbit.settingsSection)settings.section=Orbit.settingsSection;
            settings.queueReveal();
        }
    }
    SectionIndex {
        id: index;objectName: "systemSettingsIndex";Layout.fillHeight: true;Layout.preferredWidth: implicitWidth
        current: settings.section
        sections: [
            {value:12,label:"Getting around",icon:"help-browser",group:"START",description:"Find actions and learn the everyday shortcuts"},
            {value:10,label:"Appearance",icon:"color-select",group:"DESKTOP"},
            {value:2,label:"Displays",icon:"video-display",group:"DESKTOP"},
            {value:15,label:"Brightness",icon:"display-brightness",group:"DESKTOP"},
            {value:8,label:"Sound",icon:"audio-volume-high",group:"DEVICES"},
            {value:9,label:"Bluetooth",icon:"bluetooth-active",group:"DEVICES"},
            {value:5,label:"Network",icon:"network-wireless",group:"DEVICES"},
            {value:0,label:"Input",icon:"input-keyboard",group:"DEVICES"},
            {value:6,label:"Power mode",icon:"system-shutdown",group:"POWER"},
            {value:7,label:"Battery health",icon:"battery-good",group:"POWER"},
            {value:1,label:"Lock",icon:"system-lock-screen",group:"POWER"},
            {value:4,label:"Accessibility",icon:"preferences-desktop-accessibility",group:"ACCESS"},
            {value:3,label:"Shortcuts",icon:"preferences-desktop-keyboard-shortcuts",group:"ACCESS"},
            {value:16,label:"System tools",icon:"preferences-system",group:"SYSTEM"},
        ]
        onSelected: value => settings.section=value
    }
    Loader {
        id: page;objectName: "settingsPageLoader";Layout.fillWidth: true;Layout.fillHeight: true
        sourceComponent: [inputs,locks,displays,shortcuts,accessibility,network,power,battery,sound,bluetooth,appearance,null,help,null,null,brightness,systemTools][Math.max(0,Math.min(16,settings.section))]
        onLoaded: {
            pageFade.stop();page.opacity=1;
            if(settings.contentReady && !Theme.reducedMotion)pageFade.start();
            settings.queueNotice();settings.queueReveal();
        }
    }
    Component {id: help;GettingAroundPanel {onSectionRequested: value => settings.section=value}}
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
