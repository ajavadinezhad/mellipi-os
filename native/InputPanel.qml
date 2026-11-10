import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: panel;objectName: "inputPanel";property bool layoutsExpanded: false;property bool devicesExpanded: false;property bool advancedLayouts: false
    readonly property var selectedLayouts: (Input.state.layoutList || Input.state.layout || "").split(",").filter(code=>code!=="")
    function layoutLabel(code){var row=Input.layouts.find(l=>l.value===code);return row ? row.label : code;}
    function addLayout(code){if(selectedLayouts.length<4 && selectedLayouts.indexOf(code)<0)Input.setLayoutList(selectedLayouts.concat([code]).join(","));}
    function removeLayout(code){if(selectedLayouts.length>1)Input.setLayoutList(selectedLayouts.filter(value=>value!==code).join(","));}
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    ColumnLayout {
        id: content;width: panel.availableWidth;spacing: 10
        SettingsGroup {
            title: "Device"
            AudioDevicePicker {
                objectName: "inputDeviceScope";accessibleLabel: "Input device"
                devices: [{name:"",description:"All devices · defaults"}].concat((Input.devices || []).map(d => ({name:d.identifier,description:d.name+" · "+d.type})))
                selectedName: Input.state.device || "";expanded: panel.devicesExpanded
                enabled: (Input.state.sessionAvailable || Input.state.available) && !Input.state.busy && !Input.state.reading
                onToggled: panel.devicesExpanded=!panel.devicesExpanded
                onSelected: name => {panel.devicesExpanded=false;Input.selectDevice(name);}
            }
            Text {Layout.fillWidth: true;Layout.margins: 6;text: "Choose a device to customize it, or use All devices for shared defaults.";color: Theme.faint;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap}
            OrbitButton {objectName: "inputDeviceReset";visible: (Input.state.device || "")!=="";text: "Use global defaults";Accessible.name: "Remove selected device overrides and use global defaults";quiet: true;implicitHeight: 28;enabled: Input.state.available && !Input.state.busy && !Input.state.reading;onClicked: Input.resetDevice()}
        }
        SettingsGroup {
            title: "Keyboard"
            visible: !Input.state.deviceType || Input.state.deviceType==="keyboard"
            Text {visible:panel.selectedLayouts.length===0 && (Input.state.layoutName || "")!=="";Layout.fillWidth:true;Layout.margins:6;text:"Current layout: "+(Input.state.layoutName || "");color:Theme.muted;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap}
            Repeater {
                model:panel.selectedLayouts
                SettingRow {
                    required property string modelData
                    label:panel.layoutLabel(modelData)+(Input.state.layout===modelData ? " · Active" : "")
                    OrbitButton {objectName:"keyboardLayoutRemove_"+modelData;text:"Remove";Accessible.name:"Remove "+panel.layoutLabel(modelData)+" keyboard layout";quiet:true;implicitHeight:28;enabled:Input.state.available && !Input.state.busy && panel.selectedLayouts.length>1;onClicked:panel.removeLayout(modelData)}
                }
            }
            AudioDevicePicker {
                objectName:"keyboardLayoutPicker";accessibleLabel:"Add keyboard layout";chooseLabel:"Add layout…";emptyLabel:"All available layouts selected"
                devices:Input.layouts.filter(l=>panel.selectedLayouts.indexOf(l.value)<0).map(l=>({name:l.value,description:l.label}))
                selectedName:"";expanded:panel.layoutsExpanded
                enabled:Input.state.available && !Input.state.busy && panel.selectedLayouts.length<4 && devices.length>0
                onToggled:panel.layoutsExpanded=!panel.layoutsExpanded
                onSelected:name=>{panel.layoutsExpanded=false;panel.addLayout(name);}
            }
            RowLayout {
                Layout.fillWidth:true
                Text {Layout.fillWidth:true;text:"Super+Shift+Space switches layouts.";color:Theme.faint;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap}
                OrbitButton {objectName:"keyboardLayoutNext";text:"Next";Accessible.name:"Next keyboard layout";quiet:true;implicitHeight:28;enabled:Input.state.available && !Input.state.busy && !Input.state.reading && panel.selectedLayouts.length>1;onClicked:Input.nextLayout()}
            }
            OrbitButton {objectName:"keyboardLayoutsAdvanced";text:panel.advancedLayouts ? "Hide advanced codes" : "Advanced codes…";quiet:true;implicitHeight:28;onClicked:panel.advancedLayouts=!panel.advancedLayouts}
            ColumnLayout {
                visible:panel.advancedLayouts;Layout.fillWidth:true;spacing:4
                Text {Layout.fillWidth:true;text:"Up to four comma-separated XKB codes, for example us,de.";color:Theme.faint;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap}
                RowLayout {
                    Layout.fillWidth:true
                    OrbitField {id:layoutList;objectName:"keyboardLayoutList";enabled:Input.state.available && !Input.state.busy && !Input.state.reading;Accessible.name:"Keyboard layout codes";Layout.fillWidth:true;implicitHeight:30;text:Input.state.layoutList || Input.state.layout || "";maximumLength:32;onAccepted:Input.setLayoutList(text)}
                    OrbitButton {objectName:"keyboardLayoutsApply";text:"Apply";Accessible.name:"Apply keyboard layout codes";implicitHeight:28;enabled:Input.state.available && !Input.state.reading;onClicked:Input.setLayoutList(layoutList.text)}
                }
            }
            SettingRow {label: "Repeat rate";Text {text: Math.round(rate.value)+" / sec";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}}
            OrbitSlider {
                id: rate;objectName: "keyRepeatRate";Accessible.name: "Keyboard repeat rate"
                Layout.fillWidth: true;from: 1;to: 100;stepSize: 1;value: Input.state.repeatRate;enabled: Input.state.available
                onMoved: rateTimer.restart()
                Timer {id: rateTimer;interval: 150;onTriggered: Input.setRepeatRate(Math.round(rate.value))}
            }
            SettingRow {label: "Repeat delay";Text {text: Math.round(delay.value)+" ms";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}}
            OrbitSlider {
                id: delay;objectName: "keyRepeatDelay";Accessible.name: "Keyboard repeat delay"
                Layout.fillWidth: true;from: 100;to: 2000;stepSize: 50;value: Input.state.repeatDelay;enabled: Input.state.available
                onMoved: delayTimer.restart()
                Timer {id: delayTimer;interval: 150;onTriggered: Input.setRepeatDelay(Math.round(delay.value))}
            }
        }
        SettingsGroup {
            title: "Mouse & touchpad"
            visible: !Input.state.deviceType || Input.state.deviceType!=="keyboard"
            SettingRow {label: "Pointer speed";Text {text: Math.round(speed.value*100)+"%";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}}
            OrbitSlider {
                id: speed;objectName: "pointerSpeed";Accessible.name: "Pointer speed"
                Layout.fillWidth: true;from: -1;to: 1;stepSize: .05;value: Input.state.pointerSpeed;enabled: Input.state.available
                onMoved: speedTimer.restart()
                Timer {id: speedTimer;interval: 150;onTriggered: Input.setPointerSpeed(speed.value)}
            }
            SettingRow {label: "Natural scrolling";SettingToggle {objectName: "naturalScrollToggle";label: "Natural scrolling";checked: Input.state.naturalScroll;enabled: Input.state.available;onClicked: Input.setNaturalScroll(checked)}}
            SettingRow {visible: !Input.state.deviceType || Input.state.deviceType==="touchpad";label: "Tap to click";SettingToggle {objectName: "tapToClickToggle";label: "Touchpad tap to click";checked: Input.state.tapToClick;enabled: Input.state.available;onClicked: Input.setTapToClick(checked)}}
        }
        Text {Layout.fillWidth: true;text: Input.state.error || (!Input.state.available ? "Input controls require an Abstract Wayland session." : "Changes apply to matching keyboards, mice and touchpads, including devices connected later.");wrapMode: Text.Wrap;color: Input.state.error ? Theme.accent : Theme.faint;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText}
    }
}
