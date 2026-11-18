import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import "."
import "SettingReveal.js" as SettingReveal
ScrollView {
    id: view;objectName: "appearancePanel";property int section: 0;property bool customAccent: false;property bool confirmReset: false;property bool textSizeExpanded: false;property bool motionDetails: false
    function value(key) { return Orbit.appearance[key]; }
    function setValue(key, setting) {
        if(key==="accent" || key==="backgroundColor") {
            if(!/^#[0-9a-fA-F]{6}$/.test(setting))return;
            setting=setting.toLowerCase();
        }
        var change={};
        change[key]=setting;
        Orbit.applyAppearance(change);
    }
    function setMode(mode) {
        var colorMode=mode==="light" ? "light" : "dark";
        var level=mode==="black" ? "black" : "normal";
        Orbit.applyAppearance({mode:colorMode,darkLevel:level});
    }
    function revealSetting(tab,name) {
        section=Math.max(0,Math.min(2,tab));
        Qt.callLater(function(){SettingReveal.reveal(view,name);});
    }
    Connections {
        target:view.Window.window
        function onActiveFocusItemChanged() {
            Qt.callLater(function(){var window=view.Window.window;if(window)SettingReveal.scrollTo(view,window.activeFocusItem,6);});
        }
    }
    readonly property bool nativeFrames: typeof Orbit.nativeCompositor!=="undefined" && Orbit.nativeCompositor
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ColumnLayout {
        id: content;width:view.availableWidth;spacing:Theme.rowGap
        ColumnLayout {
            id: editor
            Layout.fillWidth:true;Layout.minimumWidth:0
            spacing:Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
        SettingsSegments {
            Layout.fillWidth: true;segmentWidth: Math.floor((editor.width-6)/3)
            value: view.section;options: [{label:"Style",value:0},{label:"Desktop",value:1},{label:"Motion",value:2}]
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
                ThemePicker {Layout.fillWidth:true;Layout.leftMargin:4;Layout.rightMargin:4;themeId:view.value("themePreset");previewAccent:view.value("accent");onThemeSelected:selected=>Orbit.applyTheme(selected)}
                Text {Layout.fillWidth:true;Layout.margins:4;visible: text.length>0;text:typeof Orbit.themePresets!=="undefined" ? (Orbit.themePresets.find(row=>row.id===view.value("themePreset")) || {}).description || "" : "";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
                Text {Layout.fillWidth:true;Layout.margins:4;visible: !!view.value("themePreset") && view.value("themePreset")!=="custom";text:"Editing theme colors switches to Custom.";wrapMode:Text.Wrap;color:Theme.faint;font.pixelSize:Theme.fontSize(10)}
                SettingRow {
                    label: "High contrast"
                    SettingToggle {
                        objectName: "highContrastToggle"
                        label: "High contrast for the current theme"
                        checked: view.value("highContrast")===true
                        onClicked: view.setValue("highContrast",checked)
                    }
                }
                SettingRow {
                    label: "Mode"
                    SettingsSegments {
                        objectName: "themeModeSegments"
                        value: view.value("mode") === "light" ? "light" : view.value("darkLevel")==="black" ? "black" : "dark"
                        options: [{label:"Light",value:"light"},{label:"Dark",value:"dark"},{label:"Black",value:"black"}]
                        onSelected: mode => view.setMode(mode)
                    }
                }
                SettingRow {
                    label: "Accent"
                    Repeater { model: Orbit.accentPresets
                        Rectangle {
                            required property var modelData;width: 22;height: 22;radius: Theme.corner(6);color: modelData.color
                            activeFocusOnTab: true
                            border.width: activeFocus || view.value("accent")===modelData.color ? 2 : 0;border.color: Theme.text
                            Keys.onSpacePressed: view.setValue("accent",modelData.color)
                            Keys.onReturnPressed: view.setValue("accent",modelData.color)
                            Text { anchors.centerIn: parent;text: view.value("accent")===modelData.color ? "✓" : "";color: "#15212a";font.pixelSize: Theme.fontSize(12) }
                            MouseArea { anchors.fill: parent;onClicked: view.setValue("accent",modelData.color) }
                            Accessible.name: modelData.name;Accessible.role: Accessible.Button;Accessible.onPressAction: view.setValue("accent",modelData.color)
                        }
                    }
                    IconButton { iconName: "more";implicitWidth: 24;implicitHeight: 26;hint: "Custom accent";onClicked: view.customAccent=!view.customAccent }
                }
                RowLayout {
                    visible: view.customAccent;Layout.fillWidth: true;Layout.margins: 4
                    OrbitField { id: accentInput;Layout.fillWidth: true;text: view.value("accent");maximumLength: 7;implicitHeight: 28;onAccepted: view.setValue("accent",text) }
                    IconButton { iconName: "check";hint: "Apply custom accent color";onClicked: view.setValue("accent",accentInput.text) }
                }
                SettingRow {label:"Match pointer to theme";SettingToggle {objectName:"cursorAccentToggle";label:"Use theme accent for arrow pointer";checked:view.value("cursorAccent")!==false;onClicked:view.setValue("cursorAccent",checked)}}
            }
            SettingsGroup {
                title: "Taskbar and layout"
                SettingRow {
                    label:"Text size"
                    AudioDevicePicker {
                        objectName:"appearanceTextScale";accessibleLabel:"Desktop text size"
                        chooseLabel:"Choose text size"
                        devices:[...new Set([.85,1,1.15,1.25,1.3,1.5,Theme.textScale])].sort((a,b)=>a-b)
                            .map(s=>({name:String(s),description:Math.round(s*100)+"%"}))
                        selectedName:String(Theme.textScale);expanded:view.textSizeExpanded
                        onToggled:view.textSizeExpanded=!view.textSizeExpanded
                        onSelected:name=>{view.textSizeExpanded=false;view.setValue("textScale",Number(name));}
                    }
                }
                Text {Layout.fillWidth:true;Layout.margins:4;text:"Taskbar position";color:Theme.text;font.pixelSize:Theme.fontSize(11)}
                SettingsSegments {
                    objectName:"taskbarPositionSegments"
                    Layout.fillWidth:true;Layout.margins:4
                    segmentWidth:Math.max(42,Math.floor((editor.width-22)/3))
                    value:view.value("panelPosition") || "left"
                    options:[{label:"Left",value:"left"},{label:"Bottom",value:"bottom"},{label:"Right",value:"right"}]
                    onSelected:value=>view.setValue("panelPosition",value)
                }
                SettingRow {label:"Taskbar length";SettingsSegments {objectName:"taskbarLengthSegments";value:view.value("taskbarLength") || "full";segmentWidth:80;options:[{label:"Full edge",value:"full"},{label:"Fit contents",value:"fit"}];onSelected:value=>view.setValue("taskbarLength",value)}}
                SettingRow {label:"Taskbar icon size";SettingsSegments {objectName:"taskbarIconSize";segmentWidth:52;value:view.value("taskbarIconScale") || 100;options:[75,100,125,150].map(size => ({label:size+"%",value:size}));onSelected:size=>view.setValue("taskbarIconScale",size)}}
                SettingRow {label:"Floating taskbar";SettingToggle {objectName:"floatingTaskbarToggle";label:"Floating taskbar";checked:view.value("taskbarFloating")===true;onClicked:view.setValue("taskbarFloating",checked)}}
                SettingRow {label:"Density";SettingsSegments {objectName:"densitySegments";segmentWidth:82;value:view.value("density") || (Orbit.compact ? "compact" : "comfortable");options:[{label:"Comfortable",value:"comfortable"},{label:"Compact",value:"compact"},{label:"Extra compact",value:"extra"}];onSelected:value=>view.setValue("density",value)}}
                SettingRow { label: "Shell corners";SettingsSegments { objectName:"cornerSegments"; value: view.value("corners");options: [{label:"Square",value:"square"},{label:"Soft",value:"soft"},{label:"Round",value:"rounded"}];onSelected: value => view.setValue("corners",value) } }
            }
        }
        ColumnLayout {
            visible: view.section===1;Layout.fillWidth: true;spacing: Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
            SettingsGroup {
                title: "Placement"
                SettingRow {
                    label: "Taskbar monitor"
                    SettingsSegments { segmentWidth: Math.min(68,Math.floor(200/(Orbit.outputs.length+1)));value: view.value("output");options: [{label:"Auto",value:""}].concat(Orbit.outputs.filter(o => o.name.length>0).map(o => ({label:o.name,value:o.name})));onSelected: value => view.setValue("output",value) }
                }
                SettingRow {
                    visible: Orbit.nativeCompositor
                    label: "Independent workspaces per display"
                    SettingToggle {
                        label: "Independent workspaces per display"
                        checked: view.value("independentWorkspaces")
                        onClicked: view.setValue("independentWorkspaces",checked)
                    }
                }
                SettingRow { label: "Desktop icons";SettingToggle { label: "Desktop icons";checked: view.value("desktopIcons");onClicked: view.setValue("desktopIcons",checked) } }
                SettingRow {label:"Desktop icon size";enabled:view.value("desktopIcons");SettingsSegments {objectName:"desktopIconSize";segmentWidth:52;value:view.value("desktopIconScale") || 100;options:[75,100,125,150].map(size => ({label:size+"%",value:size}));onSelected:size=>view.setValue("desktopIconScale",size)}}

            }
            SettingsGroup {
                title: "Background"
                SettingRow { label: "Style";SettingsSegments { objectName:"wallpaperStyleSegments";segmentWidth: 44;value: view.value("wallpaper")==="fold" ? "auto" : view.value("wallpaper");options: ((view.value("themePreset") && view.value("themePreset")!=="custom") || String(view.value("wallpaper") || "").startsWith("theme-") ? [{label:"Theme",value:view.value("themePreset") && view.value("themePreset")!=="custom" ? "theme-"+view.value("themePreset") : view.value("wallpaper")}] : []).concat([{label:"Auto",value:"auto"},{label:"Solid",value:"solid"},{label:"Rings",value:"orbit"},{label:"Dusk",value:"dusk"}]);onSelected: value => view.setValue("wallpaper",value) } }
                SettingRow {
                    visible: view.value("wallpaper")==="solid";label: "Color"
                    Rectangle { width: 20;height: 20;radius: Theme.corner(5);color: view.value("backgroundColor");border.color: Theme.border }
                    OrbitField { id: backgroundInput;text: view.value("backgroundColor");maximumLength: 7;implicitWidth: 92;implicitHeight: 28;onAccepted: view.setValue("backgroundColor",text) }
                    IconButton { iconName: "check";hint: "Apply solid wallpaper color";onClicked: view.setValue("backgroundColor",backgroundInput.text) }
                }
            }
            SettingsGroup {
                title: "Clock"
                SettingRow { label: "24-hour time";SettingToggle { label: "24-hour time";checked: view.value("clock24");onClicked: view.setValue("clock24",checked) } }
                SettingRow { label: "Show date";SettingToggle { label: "Show date";checked: view.value("clockDate");onClicked: view.setValue("clockDate",checked) } }
            }
        }
        ColumnLayout {
            visible: view.section===2;Layout.fillWidth: true;spacing: Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
            SettingsGroup {
                title: "Performance"
                SettingRow { label: "Shell rendering";SettingsSegments { segmentWidth: 68;value: view.value("profile");options: [{label:"Economy",value:"economy"},{label:"Balanced",value:"balanced"}];onSelected: value => view.setValue("profile",value) } }
            }
            SettingsGroup {
                title: "Animations"
                SettingRow {
                    label:"Reduce motion"
                    SettingToggle {
                        objectName:"motionReduceToggle";label:"Reduce motion across the desktop"
                        checked:view.value("reducedMotion")===true
                        onClicked:view.setValue("reducedMotion",checked)
                    }
                }
                SettingRow {
                    label:"Shell animation speed";enabled: !Theme.reducedMotion
                        && (Theme.panelMotionEnabled || Theme.controlMotionEnabled || Theme.desktopMotionEnabled)
                    SettingsSegments {
                        objectName:"motionPaceSegments";segmentWidth:62
                        value:view.value("motionPace") || "standard"
                        options:[{label:"Quick",value:"quick"},{label:"Standard",value:"standard"},{label:"Relaxed",value:"relaxed"}]
                        onSelected: pace=>view.setValue("motionPace",pace)
                    }
                }
                OrbitButton {
                    objectName:"motionCustomize";quiet:true;Layout.fillWidth:true
                    text:view.motionDetails ? "Hide individual effects" : "Customize effects…"
                    onClicked:view.motionDetails=!view.motionDetails
                }
                ColumnLayout {
                    visible:view.motionDetails;Layout.fillWidth:true
                    SettingRow {
                        label:"Panels and menus";enabled:!Theme.reducedMotion
                        SettingToggle {
                            objectName:"motionPanelToggle";label:"Animate panels, menus and Settings pages"
                            checked:view.value("panelMotion")!==false
                            onClicked:view.setValue("panelMotion",checked)
                        }
                    }
                    SettingRow {
                        label:"Control feedback";enabled:!Theme.reducedMotion
                        SettingToggle {
                            objectName:"motionControlsToggle";label:"Animate switches and controls"
                            checked:view.value("controlMotion")!==false
                            onClicked:view.setValue("controlMotion",checked)
                        }
                    }
                    SettingRow {
                        label:"Desktop and taskbar";enabled:!Theme.reducedMotion
                        SettingToggle {
                            objectName:"motionDesktopToggle";label:"Animate desktop selection and taskbar feedback"
                            checked:view.value("desktopMotion")!==false
                            onClicked:view.setValue("desktopMotion",checked)
                        }
                    }
                    SettingRow {
                        label:"Workspace transitions";enabled:!Theme.reducedMotion
                        SettingToggle {
                            objectName:"motionWorkspaceToggle";label:"Animate workspace transitions"
                            checked:view.value("workspaceMotion")!==false
                            onClicked:view.setValue("workspaceMotion",checked)
                        }
                    }
                    SettingRow {
                        visible:Orbit.nativeCompositor;label:"Window transitions";enabled:!Theme.reducedMotion
                        SettingToggle {
                            objectName:"motionWindowToggle";label:"Animate opening, minimizing and resizing windows"
                            checked:view.value("windowMotion")!==false
                            onClicked:view.setValue("windowMotion",checked)
                        }
                    }
                }
            }
            Text { text: "Economy uses shorter animations and skips extra movement. Renderer changes apply when Mellipi next starts.";font.pixelSize: Theme.fontSize(10);color: Theme.faint;Layout.fillWidth: true;wrapMode: Text.Wrap }
        }
        SettingsGroup {
            visible: view.section===0;title: "Application windows"
            SettingRow { label: "Match app theme";SettingToggle { label: "Match application light and dark preference";checked: view.value("matchApps");onClicked: view.setValue("matchApps",checked) } }
            SettingRow { visible: !Orbit.isWayland;label: "Match frame theme";SettingToggle { label: "Match application frame theme";checked: view.value("matchWindows");onClicked: view.setValue("matchWindows",checked) } }
            SettingRow {visible:view.nativeFrames;label:"Theme window borders";SettingToggle {label:"Theme application window borders";checked:view.value("matchWindows");onClicked:view.setValue("matchWindows",checked)}}
            SettingRow {
                visible: view.nativeFrames && Orbit.nativeSnapSupported === true
                label: "Snap windows at screen edges"
                SettingToggle {
                    objectName: "windowSnapToggle"
                    label: "Snap windows when dragged to screen edges"
                    checked: view.value("windowSnap") === true
                    onClicked: view.setValue("windowSnap",checked)
                }
            }
            SettingRow { visible: Orbit.isWayland && !view.nativeFrames;label: "Frame";SettingsSegments { value: view.value("frameStyle");segmentWidth: 68;options: [{label:"Native",value:"auto"},{label:"Title bar",value:"normal"},{label:"Outline",value:"pixel"}];onSelected: value => view.setValue("frameStyle",value) } }
            SettingRow { visible: Orbit.isWayland && !view.nativeFrames && view.value("frameStyle")!=="auto";label: "Border";SettingsSegments { value: view.value("frameWidth");segmentWidth: 34;options: [{label:"0",value:0},{label:"1",value:1},{label:"2",value:2},{label:"3",value:3}];onSelected: value => view.setValue("frameWidth",value) } }
            Text {visible:view.nativeFrames;Layout.fillWidth:true;Layout.margins:6;text:"Mellipi adds a thin matching border while keeping each app’s own titlebar. Older apps also receive integrated window controls.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }
        RowLayout {
            Layout.fillWidth: true
            Text {Layout.fillWidth:true;Layout.minimumWidth:0;text:"Changes save automatically.";color:Theme.muted;font.pixelSize:Theme.detailSize;wrapMode:Text.Wrap}
            OrbitButton { objectName:"appearanceReset";text: "Reset appearance…";quiet: true;implicitHeight: 26;onClicked: {view.confirmReset=true;Qt.callLater(function(){SettingReveal.reveal(view,"appearanceResetConfirm");});} }
        }
        ColumnLayout {
            visible:view.confirmReset;Layout.fillWidth:true;spacing:6
            Text {Layout.fillWidth:true;text:"Reset appearance to defaults? Pinned apps and rendering mode stay as they are.";wrapMode:Text.Wrap;color:Theme.text;font.pixelSize:Theme.fontSize(11)}
            RowLayout {
                Layout.fillWidth:true
                OrbitButton {objectName:"appearanceResetConfirm";text:"Reset appearance";onClicked:{view.confirmReset=false;Orbit.resetAppearance();}}
                OrbitButton {objectName:"appearanceResetCancel";text:"Cancel";quiet:true;onClicked:view.confirmReset=false}
            }
        }
        }
    }
}
