import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: view;objectName: "accessibilityPanel";property bool sizesExpanded: false
    readonly property var keyboardTool: DesktopTools.tools["keyboard"] || ({available:false,reason:"No compatible on-screen keyboard is installed."})
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    ColumnLayout {
        id: content;width: view.availableWidth;spacing: 10
        SettingsGroup {
            title: "Reading"
            AudioDevicePicker {
                objectName: "textScalePicker";accessibleLabel: "Desktop text size"
                devices: [.85,1,1.15,1.3,1.5].map(s => ({name:String(s),description:Math.round(s*100)+"% text size"}))
                selectedName: String(Theme.textScale);expanded: view.sizesExpanded
                onToggled: view.sizesExpanded=!view.sizesExpanded
                onSelected: name => {view.sizesExpanded=false;Orbit.setPreference("textScale",Number(name));}
            }
            SettingRow {label: "High contrast";SettingToggle {objectName: "highContrastToggle";label: "High contrast colors";checked: Theme.highContrast;onClicked: Orbit.setPreference("highContrast",checked)}}
            Text {Layout.fillWidth: true;Layout.margins: 6;text: "Text size and contrast apply to Mellipi panels. Applications keep their own text and accessibility preferences.";wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
        }
        SettingsGroup {
            title: "Keyboard and motion"
            SettingRow {label: "Reduce motion";SettingToggle {objectName: "accessibilityMotionToggle";label: "Reduce desktop motion";checked: Orbit.appearance.reducedMotion;onClicked: Orbit.setPreference("reducedMotion",checked)}}
            Text {Layout.fillWidth: true;Layout.margins: 6;text: "Use Tab to move between controls. Apps, Unfold and notifications support arrow keys and Enter or Space to activate the selected item.";wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
        }
        SettingsGroup {
            title:"Assistive tools"
            OrbitButton {text:"Open screen reader";Layout.fillWidth:true;enabled:DesktopTools.tools["screen-reader"].available;onClicked:DesktopTools.open("screen-reader")}
            OrbitButton {objectName:"accessibilityKeyboard";text:"On-screen keyboard";Layout.fillWidth:true;enabled:view.keyboardTool.available;hint:view.keyboardTool.reason || "Type in applications using the on-screen keyboard";onClicked:DesktopTools.open("keyboard")}
            Text {visible:!view.keyboardTool.available;Layout.fillWidth:true;Layout.margins:6;text:view.keyboardTool.reason || "Install wvkbd to enable the Wayland keyboard.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
            OrbitButton {text:"Input method setup";Layout.fillWidth:true;enabled:DesktopTools.tools["input-method"].available;onClicked:DesktopTools.open("input-method")}
            Text {Layout.fillWidth:true;Layout.margins:6;text:"Screen readers use the standard accessibility service. Configure an installed Fcitx or IBus engine for additional languages. The on-screen keyboard types in applications; secure-lock input is handled separately.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }

    }
}
