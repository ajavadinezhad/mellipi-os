import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
import "SettingReveal.js" as SettingReveal
ScrollView {
    id: view;objectName: "appearancePanel";property int section: 0;property bool customAccent: false;property bool confirmReset: false
    property var liveAppearance: Orbit.appearance
    property var draft: ({})
    property var pending: null
    readonly property bool dirty: Object.keys(draft).length>0
    readonly property var selectedTheme: (Orbit.themePresets || []).find(row=>row.id===value("themePreset")) || null
    readonly property bool showPreview: availableWidth>=335 || compactPreviewOpen
    readonly property bool sidePreview: availableWidth>=Math.ceil(610+Math.max(0,Theme.textScale-1)*180)
    property bool compactPreviewOpen: false
    function value(key) {
        return draft[key]!==undefined ? draft[key] : liveAppearance[key];
    }
    function stage(key,setting) {
        if((key==="accent" || key==="backgroundColor") && !/^#[0-9a-fA-F]{6}$/.test(setting))return;
        var next=Object.assign({},draft);
        if(key==="accent" || key==="backgroundColor")setting=setting.toLowerCase();
        if(setting===value(key))return;
        next[key]=setting;
        if(["accent","backgroundColor","mode","darkLevel"].includes(key) && value("themePreset")!=="custom") {
            next.themePreset="custom";
            delete next.highContrast;
        }
        draft=next;
    }
    function selectTheme(id) {
        var row=(Orbit.themePresets || []).find(theme=>theme.id===id);
        if(!row)return;
        var next=Object.assign({},draft,{
            themePreset:row.id,mode:row.mode,darkLevel:row.darkLevel,accent:row.accent,
            backgroundColor:row.background,wallpaper:row.wallpaper
        });
        if(id!==value("themePreset"))delete next.highContrast;
        draft=next;
    }
    function contrastEnabled() {
        if(draft.highContrast!==undefined)return draft.highContrast;
        var settings=liveAppearance.themeContrast || {};
        return settings[value("themePreset")] === true;
    }
    function discard() {pending=null;draft=({});}
    function commit() {
        if(!dirty || typeof Orbit.applyAppearance!=="function")return;
        pending=draft;
        Orbit.applyAppearance(draft);
    }
    onLiveAppearanceChanged: {
        if(pending && Object.keys(pending).every(key=>liveAppearance[key]===pending[key])) {
            var remaining=Object.assign({},draft);
            for(var key of Object.keys(pending))if(remaining[key]===pending[key])delete remaining[key];
            pending=null;draft=remaining;
        }
    }
    function revealSetting(tab,name) {
        section=Math.max(0,Math.min(2,tab));
        Qt.callLater(function(){SettingReveal.reveal(view,name);});
    }
    readonly property bool nativeFrames: typeof Orbit.nativeCompositor!=="undefined" && Orbit.nativeCompositor
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    GridLayout {
        id: content;width:view.availableWidth;columns:view.sidePreview ? 2 : 1
        columnSpacing:Theme.sectionGap;rowSpacing:Theme.rowGap
        SettingsGroup {
            objectName:"appearanceStudio"
            title:"Appearance studio"
            Layout.row:0;Layout.column:view.sidePreview ? 1 : 0
            Layout.alignment:Qt.AlignTop
            Layout.fillWidth:!view.sidePreview
            Layout.preferredWidth:view.sidePreview ? Math.min(370,Math.round(view.availableWidth*.39)) : 0
            OrbitButton {
                visible:view.availableWidth<335;quiet:true;Layout.fillWidth:true
                text:view.showPreview ? "Hide desktop preview" : "Show desktop preview"
                onClicked:view.compactPreviewOpen=!view.compactPreviewOpen
            }
            Loader {
                active:view.showPreview;visible:active
                Layout.fillWidth:true;Layout.leftMargin:4;Layout.rightMargin:4
                sourceComponent:AppearancePreview {
                    mode:view.value("mode") || "dark";black:view.value("darkLevel")==="black"
                    accent:view.value("accent") || Theme.accent
                    backgroundColor:view.value("backgroundColor") || Theme.background
                    wallpaper:view.value("wallpaper") || "auto";themeRow:view.selectedTheme
                    highContrast:view.contrastEnabled()
                    taskbarPosition:view.value("panelPosition") || "left"
                    taskbarLength:view.value("taskbarLength") || "full"
                    taskbarFloating:view.value("taskbarFloating")===true
                    iconScale:view.value("taskbarIconScale") || 100
                    desktopIconScale:view.value("desktopIconScale") || 100
                    desktopIcons:view.value("desktopIcons")!==false
                    textScale:view.value("textScale") || 1
                    density:view.value("density") || "compact"
                    corners:view.value("corners") || "rounded"
                    matchWindows:view.value("matchWindows")!==false
                    economy:view.value("profile")==="economy"
                }
            }
            Text {
                Layout.fillWidth:true;Layout.margins:4;wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.detailSize
                text:view.dirty ? "Preview only. Apply to update your desktop." : "Adjust the preview, then apply your changes."
            }
            RowLayout {
                visible:view.dirty;Layout.fillWidth:true;Layout.minimumWidth:0
                OrbitButton {objectName:"appearanceDiscard";text:"Discard";Layout.fillWidth:true;Layout.minimumWidth:0;quiet:true;onClicked:view.discard()}
                OrbitButton {objectName:"appearanceApply";text:"Apply";Layout.fillWidth:true;Layout.minimumWidth:0;accent:true;onClicked:view.commit()}
            }
        }
        ColumnLayout {
            id: editor
            Layout.row:view.sidePreview ? 0 : 1;Layout.column:0;Layout.alignment:Qt.AlignTop
            Layout.fillWidth:true;Layout.minimumWidth:0
            spacing:Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
        SettingsSegments {
            Layout.fillWidth: true;segmentWidth: Math.floor((editor.width-6)/3)
            value: view.section;options: [{label:"Style",value:0},{label:"Desktop",value:1},{label:"Motion & speed",value:2}]
            onSelected: value => view.section=value
        }
        ColumnLayout {
            visible: view.section===0;Layout.fillWidth: true;spacing: Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
            SettingsGroup {
                title: "Theme"
                Text {
                    visible: view.nativeFrames && typeof Orbit.nativePaletteSupported!=="undefined" && !Orbit.nativePaletteSupported && view.value("themePreset") && view.value("themePreset")!=="custom"
                    Layout.fillWidth:true;Layout.margins:4
                    text:"Window border colors update at your next sign-in."
                    wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)
                }
                ThemePicker {Layout.fillWidth:true;Layout.leftMargin:4;Layout.rightMargin:4;themeId:view.value("themePreset");previewAccent:view.value("accent");onThemeSelected:selected=>view.selectTheme(selected)}
                Text {Layout.fillWidth:true;Layout.margins:4;visible: text.length>0;text:typeof Orbit.themePresets!=="undefined" ? (Orbit.themePresets.find(row=>row.id===view.value("themePreset")) || {}).description || "" : "";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
                Text {Layout.fillWidth:true;Layout.margins:4;visible: !!view.value("themePreset") && view.value("themePreset")!=="custom";text:"Editing theme colors switches to Custom.";wrapMode:Text.Wrap;color:Theme.faint;font.pixelSize:Theme.fontSize(10)}
                SettingRow {
                    label: "High contrast"
                    SettingToggle {
                        objectName: "highContrastToggle"
                        label: "High contrast for the current theme"
                        checked: view.contrastEnabled()
                        onClicked: view.stage("highContrast",checked)
                    }
                }
                SettingRow {
                    label: "Mode"
                    SettingsSegments {
                        objectName: "themeModeSegments"
                        value: view.value("mode") === "light" ? "light" : view.value("darkLevel")==="black" ? "black" : "dark"
                        options: [{label:"Light",value:"light"},{label:"Dark",value:"dark"},{label:"Black",value:"black"}]
                        onSelected: value => {
                            view.stage("mode",value === "light" ? "light" : "dark");
                            view.stage("darkLevel",value === "black" ? "black" : "normal");
                        }
                    }
                }
                SettingRow {
                    label: "Accent"
                    Repeater { model: Orbit.accentPresets
                        Rectangle {
                            required property var modelData;width: 22;height: 22;radius: Theme.corner(6);color: modelData.color
                            activeFocusOnTab: true
                            border.width: activeFocus || view.value("accent")===modelData.color ? 2 : 0;border.color: Theme.text
                            Keys.onSpacePressed: view.stage("accent",modelData.color)
                            Keys.onReturnPressed: view.stage("accent",modelData.color)
                            Text { anchors.centerIn: parent;text: view.value("accent")===modelData.color ? "✓" : "";color: "#15212a";font.pixelSize: Theme.fontSize(12) }
                            MouseArea { anchors.fill: parent;onClicked: view.stage("accent",modelData.color) }
                            Accessible.name: modelData.name;Accessible.role: Accessible.Button;Accessible.onPressAction: view.stage("accent",modelData.color)
                        }
                    }
                    IconButton { iconName: "more";implicitWidth: 24;implicitHeight: 26;hint: "Custom accent";onClicked: view.customAccent=!view.customAccent }
                }
                RowLayout {
                    visible: view.customAccent;Layout.fillWidth: true;Layout.margins: 4
                    OrbitField { id: accentInput;Layout.fillWidth: true;text: view.value("accent");maximumLength: 7;implicitHeight: 28;onAccepted: view.stage("accent",text) }
                    IconButton { iconName: "check";hint: "Apply custom accent color";onClicked: view.stage("accent",accentInput.text) }
                }
                SettingRow {label:"Match pointer to theme";SettingToggle {objectName:"cursorAccentToggle";label:"Use theme accent for arrow pointer";checked:view.value("cursorAccent")!==false;onToggled:view.stage("cursorAccent",checked)}}
            }
            SettingsGroup {
                title: "Taskbar and layout"
                SettingRow {
                    label:"Text size"
                    SettingsSegments {
                        objectName:"appearanceTextScale";segmentWidth:50
                        value:view.value("textScale") || 1
                        options:[0.85,1,1.25,1.5].map(scale=>({label:Math.round(scale*100)+"%",value:scale}))
                        onSelected:scale=>view.stage("textScale",scale)
                    }
                }
                Text {Layout.fillWidth:true;Layout.margins:4;text:"Taskbar position";color:Theme.text;font.pixelSize:Theme.fontSize(11)}
                SettingsSegments {
                    objectName:"taskbarPositionSegments"
                    Layout.fillWidth:true;Layout.margins:4
                    segmentWidth:Math.max(42,Math.floor((editor.width-22)/3))
                    value:view.value("panelPosition") || "left"
                    options:[{label:"Left",value:"left"},{label:"Bottom",value:"bottom"},{label:"Right",value:"right"}]
                    onSelected:value=>view.stage("panelPosition",value)
                }
                SettingRow {label:"Taskbar length";SettingsSegments {objectName:"taskbarLengthSegments";value:view.value("taskbarLength") || "full";segmentWidth:80;options:[{label:"Full edge",value:"full"},{label:"Fit contents",value:"fit"}];onSelected:value=>view.stage("taskbarLength",value)}}
                SettingRow {label:"Taskbar icon size";SettingsSegments {objectName:"taskbarIconSize";segmentWidth:52;value:view.value("taskbarIconScale") || 100;options:[75,100,125,150].map(size => ({label:size+"%",value:size}));onSelected:size=>view.stage("taskbarIconScale",size)}}
                SettingRow {label:"Floating taskbar";SettingToggle {objectName:"floatingTaskbarToggle";label:"Floating taskbar";checked:view.value("taskbarFloating")===true;onToggled:view.stage("taskbarFloating",checked)}}
                SettingRow {label:"Density";SettingsSegments {objectName:"densitySegments";segmentWidth:82;value:view.value("density") || (Orbit.compact ? "compact" : "comfortable");options:[{label:"Comfortable",value:"comfortable"},{label:"Compact",value:"compact"},{label:"Extra compact",value:"extra"}];onSelected:value=>view.stage("density",value)}}
                SettingRow { label: "Shell corners";SettingsSegments { objectName:"cornerSegments"; value: view.value("corners");options: [{label:"Square",value:"square"},{label:"Soft",value:"soft"},{label:"Round",value:"rounded"}];onSelected: value => view.stage("corners",value) } }
            }
        }
        ColumnLayout {
            visible: view.section===1;Layout.fillWidth: true;spacing: Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
            SettingsGroup {
                title: "Placement"
                SettingRow {
                    label: "Taskbar monitor"
                    SettingsSegments { segmentWidth: Math.min(68,Math.floor(200/(Orbit.outputs.length+1)));value: view.value("output");options: [{label:"Auto",value:""}].concat(Orbit.outputs.filter(o => o.name.length>0).map(o => ({label:o.name,value:o.name})));onSelected: value => view.stage("output",value) }
                }
                SettingRow { label: "Desktop icons";SettingToggle { label: "Desktop icons";checked: view.value("desktopIcons");onToggled: view.stage("desktopIcons",checked) } }
                SettingRow {label:"Desktop icon size";enabled:view.value("desktopIcons");SettingsSegments {objectName:"desktopIconSize";segmentWidth:52;value:view.value("desktopIconScale") || 100;options:[75,100,125,150].map(size => ({label:size+"%",value:size}));onSelected:size=>view.stage("desktopIconScale",size)}}

            }
            SettingsGroup {
                title: "Background"
                SettingRow { label: "Style";SettingsSegments { objectName:"wallpaperStyleSegments";segmentWidth: 44;value: view.value("wallpaper")==="fold" ? "auto" : view.value("wallpaper");options: ((view.value("themePreset") && view.value("themePreset")!=="custom") || String(view.value("wallpaper") || "").startsWith("theme-") ? [{label:"Theme",value:view.value("themePreset") && view.value("themePreset")!=="custom" ? "theme-"+view.value("themePreset") : view.value("wallpaper")}] : []).concat([{label:"Auto",value:"auto"},{label:"Solid",value:"solid"},{label:"Rings",value:"orbit"},{label:"Dusk",value:"dusk"}]);onSelected: value => view.stage("wallpaper",value) } }
                SettingRow {
                    visible: view.value("wallpaper")==="solid";label: "Color"
                    Rectangle { width: 20;height: 20;radius: Theme.corner(5);color: view.value("backgroundColor");border.color: Theme.border }
                    OrbitField { id: backgroundInput;text: view.value("backgroundColor");maximumLength: 7;implicitWidth: 92;implicitHeight: 28;onAccepted: view.stage("backgroundColor",text) }
                    IconButton { iconName: "check";hint: "Apply solid wallpaper color";onClicked: view.stage("backgroundColor",backgroundInput.text) }
                }
            }
            SettingsGroup {
                title: "Clock"
                SettingRow { label: "24-hour time";SettingToggle { label: "24-hour time";checked: view.value("clock24");onToggled: view.stage("clock24",checked) } }
                SettingRow { label: "Show date";SettingToggle { label: "Show date";checked: view.value("clockDate");onToggled: view.stage("clockDate",checked) } }
            }
        }
        ColumnLayout {
            visible: view.section===2;Layout.fillWidth: true;spacing: Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
            SettingsGroup {
                title: "Performance"
                SettingRow { label: "Shell rendering";SettingsSegments { segmentWidth: 68;value: view.value("profile");options: [{label:"Economy",value:"economy"},{label:"Balanced",value:"balanced"}];onSelected: value => view.stage("profile",value) } }
            }
            SettingsGroup {
                title: "Animation"
                SettingRow {
                    visible: Orbit.nativeCompositor
                    label: "Independent workspaces per display"
                    SettingToggle {
                        label: "Independent workspaces per display"
                        checked: view.value("independentWorkspaces")
                        onToggled: view.stage("independentWorkspaces",checked)
                    }
                }
                SettingRow { label: "Workspace transitions";enabled: !view.value("reducedMotion");SettingToggle { label: "Workspace transitions";checked: view.value("workspaceMotion");onToggled: view.stage("workspaceMotion",checked) } }
                SettingRow {label:"Reduce motion";Text {text:view.value("reducedMotion") ? "On" : "Off";color:Theme.muted;font.pixelSize:Theme.fontSize(11)}OrbitButton {objectName:"motionAccessibilityLink";text:"Accessibility…";quiet:true;implicitHeight:28;onClicked:Orbit.openSettingsSection(4)}}
            }
            Text { text: "Economy uses fewer effects. Rendering changes apply when Mellipi next starts.";font.pixelSize: Theme.fontSize(10);color: Theme.faint;Layout.fillWidth: true;wrapMode: Text.Wrap }
        }
        SettingsGroup {
            visible: view.section===0;title: "Application windows"
            SettingRow { label: "Match app theme";SettingToggle { label: "Match application light and dark preference";checked: view.value("matchApps");onToggled: view.stage("matchApps",checked) } }
            SettingRow { visible: !Orbit.isWayland;label: "Match frame theme";SettingToggle { label: "Match application frame theme";checked: view.value("matchWindows");onToggled: view.stage("matchWindows",checked) } }
            SettingRow {visible:view.nativeFrames;label:"Theme window borders";SettingToggle {label:"Theme application window borders";checked:view.value("matchWindows");onToggled:view.stage("matchWindows",checked)}}
            SettingRow {
                visible: view.nativeFrames && Orbit.nativeSnapSupported === true
                label: "Snap windows at screen edges"
                SettingToggle {
                    objectName: "windowSnapToggle"
                    label: "Snap windows when dragged to screen edges"
                    checked: view.value("windowSnap") === true
                    onToggled: view.stage("windowSnap",checked)
                }
            }
            SettingRow { visible: Orbit.isWayland && !view.nativeFrames;label: "Frame";SettingsSegments { value: view.value("frameStyle");segmentWidth: 68;options: [{label:"Native",value:"auto"},{label:"Title bar",value:"normal"},{label:"Outline",value:"pixel"}];onSelected: value => view.stage("frameStyle",value) } }
            SettingRow { visible: Orbit.isWayland && !view.nativeFrames && view.value("frameStyle")!=="auto";label: "Border";SettingsSegments { value: view.value("frameWidth");segmentWidth: 34;options: [{label:"0",value:0},{label:"1",value:1},{label:"2",value:2},{label:"3",value:3}];onSelected: value => view.stage("frameWidth",value) } }
            Text {visible:view.nativeFrames;Layout.fillWidth:true;Layout.margins:6;text:"Mellipi adds a thin matching border while keeping each app’s own titlebar. Older apps also receive integrated window controls.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }
        RowLayout {
            Layout.fillWidth: true
            OrbitButton {
                text:"Review changes";visible:view.dirty;quiet:true;Layout.fillWidth:true;Layout.minimumWidth:0
                onClicked:Qt.callLater(function(){SettingReveal.reveal(view,"appearanceApply");})
            }
            Item {visible:!view.dirty;Layout.fillWidth:true}
            OrbitButton { objectName:"appearanceReset";text: "Reset appearance…";quiet: true;implicitHeight: 26;onClicked: {view.confirmReset=true;Qt.callLater(function(){SettingReveal.reveal(view,"appearanceResetConfirm");});} }
        }
        ColumnLayout {
            visible:view.confirmReset;Layout.fillWidth:true;spacing:6
            Text {Layout.fillWidth:true;text:"Reset appearance to defaults? Pinned apps and rendering mode stay as they are.";wrapMode:Text.Wrap;color:Theme.text;font.pixelSize:Theme.fontSize(11)}
            RowLayout {
                Layout.fillWidth:true
                OrbitButton {objectName:"appearanceResetConfirm";text:"Reset appearance";onClicked:{view.confirmReset=false;view.discard();Orbit.resetAppearance();}}
                OrbitButton {objectName:"appearanceResetCancel";text:"Cancel";quiet:true;onClicked:view.confirmReset=false}
            }
        }
        }
    }
}
