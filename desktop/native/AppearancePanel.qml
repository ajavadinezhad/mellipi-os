import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
import "SettingReveal.js" as SettingReveal
ScrollView {
    id: view;objectName: "appearancePanel";property int section: 0;property bool customAccent: false;property bool confirmReset: false
    function revealSetting(tab,name) {
        section=Math.max(0,Math.min(2,tab));
        Qt.callLater(function(){SettingReveal.reveal(view,name);});
    }
    readonly property bool nativeFrames: typeof Orbit.nativeCompositor!=="undefined" && Orbit.nativeCompositor
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    ColumnLayout {
        id: content;width: view.availableWidth;spacing: 12
        SettingsSegments {
            Layout.fillWidth: true;segmentWidth: Math.floor((view.availableWidth-6)/3)
            value: view.section;options: [{label:"Style",value:0},{label:"Desktop",value:1},{label:"Motion & speed",value:2}]
            onSelected: value => view.section=value
        }
        ColumnLayout {
            visible: view.section===0;Layout.fillWidth: true;spacing: 12
            SettingsGroup {
                title: "Theme"
                Text {Layout.fillWidth:true;Layout.margins:4;text: "Choose a complete theme, or adjust its colors below.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
                ColumnLayout {
                    objectName: "themeHighContrastNotice"
                    visible: Orbit.appearance.highContrast===true
                    Layout.fillWidth:true;Layout.margins:4;spacing:4
                    Text {
                        Layout.fillWidth:true
                        text:"High contrast is on. It overrides theme colors for readability; your theme stays selected. Turn it off in Accessibility to see each theme’s full palette."
                        wrapMode:Text.Wrap;color:Theme.text;font.pixelSize:Theme.fontSize(11)
                    }
                    OrbitButton {
                        objectName:"themeAccessibilityLink"
                        text:"Open Accessibility…";quiet:true;implicitHeight:28
                        onClicked:Orbit.openSettingsSection(4)
                    }
                }
                Text {
                    visible: view.nativeFrames && typeof Orbit.nativePaletteSupported!=="undefined" && !Orbit.nativePaletteSupported && Orbit.appearance.themePreset && Orbit.appearance.themePreset!=="custom"
                    Layout.fillWidth:true;Layout.margins:4
                    text:"Full native window-border colors activate after your next Abstract login."
                    wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)
                }
                ThemePicker {Layout.fillWidth:true;Layout.leftMargin:4;Layout.rightMargin:4}
                Text {Layout.fillWidth:true;Layout.margins:4;text:typeof Orbit.themePresets!=="undefined" ? (Orbit.themePresets.find(row=>row.id===Orbit.appearance.themePreset) || {}).description || "Choose a theme to match the desktop, windows and lock screen." : "";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
                Text {Layout.fillWidth:true;Layout.margins:4;text:Orbit.appearance.themePreset && Orbit.appearance.themePreset!=="custom" ? "Theme selected · color changes create a custom style" : "Custom style";wrapMode:Text.Wrap;color:Theme.faint;font.pixelSize:Theme.fontSize(10)}
                SettingRow {
                    label: "Mode"
                    SettingsSegments {
                        objectName: "themeModeSegments"
                        value: Orbit.themeMode === "light" ? "light" : Theme.black ? "black" : "dark"
                        options: [{label:"Light",value:"light"},{label:"Dark",value:"dark"},{label:"Black",value:"black"}]
                        onSelected: value => {
                            Orbit.setPreference("mode",value === "light" ? "light" : "dark");
                            Orbit.setPreference("darkLevel",value === "black" ? "black" : "normal");
                        }
                    }
                }
                SettingRow {
                    label: "Accent"
                    Repeater { model: Orbit.accentPresets
                        Rectangle {
                            required property var modelData;width: 22;height: 22;radius: Theme.corner(6);color: modelData.color
                            border.width: Orbit.accentColor===modelData.color ? 2 : 0;border.color: Theme.text
                            Text { anchors.centerIn: parent;text: Orbit.accentColor===modelData.color ? "✓" : "";color: "#15212a";font.pixelSize: Theme.fontSize(12) }
                            MouseArea { anchors.fill: parent;onClicked: Orbit.setPreference("accent",modelData.color) }
                            Accessible.name: modelData.name;Accessible.role: Accessible.Button;Accessible.onPressAction: Orbit.setPreference("accent",modelData.color)
                        }
                    }
                    OrbitButton { text: "…";quiet: true;implicitWidth: 24;implicitHeight: 26;hint: "Custom accent";onClicked: view.customAccent=!view.customAccent }
                }
                RowLayout {
                    visible: view.customAccent;Layout.fillWidth: true;Layout.margins: 4
                    OrbitField { id: accentInput;Layout.fillWidth: true;text: Orbit.accentColor;maximumLength: 7;implicitHeight: 28;onAccepted: Orbit.setPreference("accent",text) }
                    OrbitButton { text: "Apply";implicitHeight: 28;onClicked: Orbit.setPreference("accent",accentInput.text) }
                }
                SettingRow {label:"Pointer";SettingToggle {objectName:"cursorAccentToggle";label:"Use theme accent for arrow pointer";checked:Orbit.appearance.cursorAccent!==false;onToggled:Orbit.setPreference("cursorAccent",checked)}Text {text:"Use theme accent";color:Theme.muted;font.pixelSize:Theme.fontSize(11)}}
            }
            SettingsGroup {
                title: "Taskbar and layout"
                Text {Layout.fillWidth:true;Layout.margins:4;text:"Taskbar position";color:Theme.text;font.pixelSize:Theme.fontSize(11)}
                SettingsSegments {
                    objectName:"taskbarPositionSegments"
                    Layout.fillWidth:true;Layout.margins:4
                    segmentWidth:Math.max(42,Math.floor((view.availableWidth-22)/4))
                    value:Orbit.appearance.panelPosition || "left"
                    options:[{label:"Top",value:"top"},{label:"Bottom",value:"bottom"},{label:"Left",value:"left"},{label:"Right",value:"right"}]
                    onSelected:value=>Orbit.setPreference("panelPosition",value)
                }
                SettingRow {label:"Taskbar length";SettingsSegments {objectName:"taskbarLengthSegments";value:Orbit.appearance.taskbarLength || "full";segmentWidth:80;options:[{label:"Full edge",value:"full"},{label:"Fit contents",value:"fit"}];onSelected:value=>Orbit.setPreference("taskbarLength",value)}}
                SettingRow {label:"Floating taskbar";SettingToggle {objectName:"floatingTaskbarToggle";label:"Floating taskbar";checked:Orbit.appearance.taskbarFloating===true;onToggled:Orbit.setPreference("taskbarFloating",checked)}}
                SettingRow {label:"Density";SettingsSegments {objectName:"densitySegments";segmentWidth:82;value:Orbit.appearance.density || (Orbit.compact ? "compact" : "comfortable");options:[{label:"Comfortable",value:"comfortable"},{label:"Compact",value:"compact"},{label:"Extra compact",value:"extra"}];onSelected:value=>Orbit.setPreference("density",value)}}
                SettingRow { label: "Shell corners";SettingsSegments { objectName:"cornerSegments"; value: Orbit.appearance.corners;options: [{label:"Square",value:"square"},{label:"Soft",value:"soft"},{label:"Round",value:"rounded"}];onSelected: value => Orbit.setPreference("corners",value) } }
            }
        }
        ColumnLayout {
            visible: view.section===1;Layout.fillWidth: true;spacing: 12
            SettingsGroup {
                title: "Placement"
                SettingRow {
                    label: "Taskbar monitor"
                    SettingsSegments { segmentWidth: Math.min(68,Math.floor(200/(Orbit.outputs.length+1)));value: Orbit.appearance.output;options: [{label:"Auto",value:""}].concat(Orbit.outputs.filter(o => o.name.length>0).map(o => ({label:o.name,value:o.name})));onSelected: value => Orbit.setPreference("output",value) }
                }
                SettingRow { label: "Desktop icons";SettingToggle { label: "Desktop icons";checked: Orbit.appearance.desktopIcons;onToggled: Orbit.setPreference("desktopIcons",checked) } }
            }
            SettingsGroup {
                title: "Background"
                SettingRow { label: "Style";SettingsSegments { objectName:"wallpaperStyleSegments";segmentWidth: 44;value: Orbit.appearance.wallpaper==="fold" ? "auto" : Orbit.appearance.wallpaper;options: ((Orbit.appearance.themePreset && Orbit.appearance.themePreset!=="custom") || Orbit.appearance.themeWallpaper ? [{label:"Theme",value:Orbit.appearance.themePreset && Orbit.appearance.themePreset!=="custom" ? "theme-"+Orbit.appearance.themePreset : Orbit.appearance.wallpaper}] : []).concat([{label:"Auto",value:"auto"},{label:"Solid",value:"solid"},{label:"Rings",value:"orbit"},{label:"Dusk",value:"dusk"}]);onSelected: value => Orbit.setPreference("wallpaper",value) } }
                SettingRow {
                    visible: Orbit.appearance.wallpaper==="solid";label: "Color"
                    Rectangle { width: 20;height: 20;radius: Theme.corner(5);color: Orbit.appearance.backgroundColor;border.color: Theme.border }
                    OrbitField { id: backgroundInput;text: Orbit.appearance.backgroundColor;maximumLength: 7;implicitWidth: 92;implicitHeight: 28;onAccepted: Orbit.setPreference("backgroundColor",text) }
                    OrbitButton { text: "Apply";implicitHeight: 26;onClicked: Orbit.setPreference("backgroundColor",backgroundInput.text) }
                }
            }
            SettingsGroup {
                title: "Clock"
                SettingRow { label: "24-hour time";SettingToggle { label: "24-hour time";checked: Orbit.appearance.clock24;onToggled: Orbit.setPreference("clock24",checked) } }
                SettingRow { label: "Show date";SettingToggle { label: "Show date";checked: Orbit.appearance.clockDate;onToggled: Orbit.setPreference("clockDate",checked) } }
            }
        }
        ColumnLayout {
            visible: view.section===2;Layout.fillWidth: true;spacing: 12
            SettingsGroup {
                title: "Performance"
                SettingRow { label: "Shell rendering";SettingsSegments { segmentWidth: 68;value: Orbit.economy ? "economy" : "balanced";options: [{label:"Economy",value:"economy"},{label:"Balanced",value:"balanced"}];onSelected: value => Orbit.setPreference("profile",value) } }
            }
            SettingsGroup {
                title: "Animation"
                SettingRow { label: "Workspace transitions";enabled: !Orbit.appearance.reducedMotion;SettingToggle { label: "Workspace transitions";checked: Orbit.workspaceMotion;onToggled: Orbit.setPreference("workspaceMotion",checked) } }
                SettingRow {label:"Reduce motion";Text {text:Orbit.appearance.reducedMotion ? "On" : "Off";color:Theme.muted;font.pixelSize:Theme.fontSize(11)}OrbitButton {objectName:"motionAccessibilityLink";text:"Accessibility…";quiet:true;implicitHeight:28;onClicked:Orbit.openSettingsSection(4)}}
            }
            Text { text: "Economy uses fewer effects. Rendering changes apply when Abstract next starts.";font.pixelSize: Theme.fontSize(10);color: Theme.faint;Layout.fillWidth: true;wrapMode: Text.Wrap }
        }
        SettingsGroup {
            visible: view.section===0;title: "Application windows"
            SettingRow { label: "Match app theme";SettingToggle { label: "Match application light and dark preference";checked: Orbit.appearance.matchApps;onToggled: Orbit.setPreference("matchApps",checked) } }
            SettingRow { visible: !Orbit.isWayland;label: "Match frame theme";SettingToggle { label: "Match application frame theme";checked: Orbit.appearance.matchWindows;onToggled: Orbit.setPreference("matchWindows",checked) } }
            SettingRow {visible:view.nativeFrames;label:"Theme window borders";SettingToggle {label:"Theme application window borders";checked:Orbit.appearance.matchWindows;onToggled:Orbit.setPreference("matchWindows",checked)}}
            SettingRow { visible: Orbit.isWayland && !view.nativeFrames;label: "Frame";SettingsSegments { value: Orbit.appearance.frameStyle;segmentWidth: 68;options: [{label:"Native",value:"auto"},{label:"Title bar",value:"normal"},{label:"Outline",value:"pixel"}];onSelected: value => Orbit.setPreference("frameStyle",value) } }
            SettingRow { visible: Orbit.isWayland && !view.nativeFrames && Orbit.appearance.frameStyle!=="auto";label: "Border";SettingsSegments { value: Orbit.appearance.frameWidth;segmentWidth: 34;options: [{label:"0",value:0},{label:"1",value:1},{label:"2",value:2},{label:"3",value:3}];onSelected: value => Orbit.setPreference("frameWidth",value) } }
            Text {visible:view.nativeFrames;Layout.fillWidth:true;Layout.margins:6;text:"Abstract adds a thin matching border while keeping each app’s own titlebar. Older apps also receive integrated window controls.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }
        RowLayout {
            Layout.fillWidth: true
            Text { text: "Saved automatically";font.pixelSize: Theme.fontSize(10);color: Theme.faint;Layout.fillWidth: true }
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
