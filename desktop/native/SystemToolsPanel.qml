import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
import "SettingReveal.js" as SettingReveal
ScrollView {
    id: panel;objectName:"systemToolsPanel";clip:true;contentWidth:availableWidth
    property string section:typeof DesktopTools.state!=="undefined" ? "defaults" : "tools"
    readonly property bool integrated:typeof DesktopTools.state!=="undefined"
    readonly property var data:integrated ? DesktopTools.state : ({busy:false,error:"",gioAvailable:false})
    property int lastViewSerial:0
    function applyViewRequest(){
        var request=typeof DesktopTools.viewRequest!=="undefined" ? DesktopTools.viewRequest : ({});
        if(request.serial && request.serial!==lastViewSerial){lastViewSerial=request.serial;panel.section=request.name;}
    }
    function revealSetting(tab,target){panel.section=["defaults","startup","devices","tools"][Math.max(0,Math.min(3,tab))];Qt.callLater(function(){SettingReveal.reveal(panel,target);});}
    implicitHeight:440
    ScrollBar.horizontal.policy:ScrollBar.AlwaysOff
    Component.onCompleted:{panel.applyViewRequest();if(typeof DesktopTools.setActive==="function")DesktopTools.setActive(true)}
    Component.onDestruction:if(typeof DesktopTools.setActive==="function")DesktopTools.setActive(false)
    Connections {target:DesktopTools;ignoreUnknownSignals:true;function onViewRequested(name){panel.section=name;}function onChanged(){panel.applyViewRequest();}}
    ColumnLayout {
        width:panel.availableWidth;spacing:12
        SettingsSegments {
            objectName:"systemToolTabs"
            Layout.fillWidth:true;segmentWidth:Math.floor((panel.availableWidth-6)/4);value:panel.section
            options:[{label:"Apps",value:"defaults"},{label:"Startup",value:"startup"},{label:"Devices",value:"devices"},{label:"Tools",value:"tools"}]
            onSelected:value=>panel.section=value
        }
        Text {visible:!!panel.data.error;Layout.fillWidth:true;text:panel.data.error || "";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap;textFormat:Text.PlainText}
        ColumnLayout {
            visible:panel.section==="defaults";Layout.fillWidth:true;spacing:8
            Text {Layout.fillWidth:true;text:"Default applications";color:Theme.text;font.pixelSize:Theme.fontSize(14)}
            Text {Layout.fillWidth:true;text:"Choose which app opens each type of content.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
            SettingsChoice {
                id:typePicker;objectName:"defaultTypePicker";Layout.fillWidth:true
                model:typeof DesktopTools.defaultTypes!=="undefined" ? DesktopTools.defaultTypes : [];textRole:"name"
                Accessible.name:"Content type"
                currentIndex:Math.max(0,model.findIndex(row=>row.id===DesktopTools.defaultType))
                onActivated:index=>DesktopTools.selectDefaultType(model[index].id)
            }
            Repeater {
                model:typeof DesktopTools.defaultApplications!=="undefined" ? DesktopTools.defaultApplications : []
                delegate:OrbitButton {
                    required property var modelData
                    objectName:"defaultApp_"+modelData.id
                    Layout.fillWidth:true;text:(modelData.selected ? "✓  " : "")+modelData.name
                    enabled:!panel.data.busy;quiet:!modelData.selected
                    Accessible.name:modelData.name+(modelData.selected ? ", current default" : "")
                    onClicked:DesktopTools.setDefaultApplication(modelData.id)
                }
            }
            Text {visible:!panel.data.gioAvailable || (typeof DesktopTools.defaultApplications!=="undefined" && !DesktopTools.defaultApplications.length);Layout.fillWidth:true;text:panel.data.gioAvailable ? "No compatible apps are installed for this type. Install an app through Software in Tools." : "Default applications requires GIO support. Install the distribution’s Python GObject/GIO package.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
        }
        ColumnLayout {
            visible:panel.section==="startup";Layout.fillWidth:true;spacing:8
            RowLayout {Layout.fillWidth:true;Text {Layout.fillWidth:true;objectName:"startupApplications";text:"Startup applications";color:Theme.text;font.pixelSize:Theme.fontSize(14)}OrbitButton {text:"Refresh";quiet:true;implicitHeight:28;onClicked:DesktopTools.refreshStartup()}}
            RowLayout {
                Layout.fillWidth:true;spacing:6
                SettingsChoice {
                    id:startupChoice;objectName:"startupAppPicker";Layout.fillWidth:true;Layout.minimumWidth:0
                    Accessible.name:"Application to start at login"
                    model:[{id:"",name:"Choose an app…"}].concat(typeof Orbit.launcherApps!=="undefined" ? Orbit.launcherApps : [])
                    textRole:"name"
                }
                OrbitButton {objectName:"startupAppAdd";text:"Add";implicitHeight:30;enabled:!panel.data.busy && panel.data.gioAvailable && startupChoice.currentIndex>0;onClicked:{DesktopTools.addStartupApplication(startupChoice.model[startupChoice.currentIndex].id);startupChoice.currentIndex=0;}}
            }
            Text {Layout.fillWidth:true;text:"Changes apply at your next login. Turning an entry off does not close its running app.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
            Repeater {
                model:typeof DesktopTools.startupApps!=="undefined" ? DesktopTools.startupApps : []
                delegate:SettingRow {
                    required property var modelData
                    label:modelData.name
                    SettingToggle {objectName:"startupToggle_"+modelData.id;label:modelData.name;checked:modelData.enabled;enabled:!panel.data.busy && (modelData.available || modelData.enabled);onClicked:DesktopTools.setStartupEnabled(modelData.id,checked)}
                }
            }
            Text {visible:typeof DesktopTools.startupApps==="undefined" || !DesktopTools.startupApps.length;Layout.fillWidth:true;text:"No additional startup applications for this desktop.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
        }
        ColumnLayout {
            visible:panel.section==="devices";Layout.fillWidth:true;spacing:8
            Text {Layout.fillWidth:true;objectName:"removableDevices";text:"Removable devices";color:Theme.text;font.pixelSize:Theme.fontSize(14)}
            Repeater {
                model:typeof DesktopTools.devices!=="undefined" ? DesktopTools.devices : []
                delegate:SettingsGroup {
                    required property var modelData
                    title:modelData.name
                    Text {Layout.fillWidth:true;text:modelData.mounted ? "Mounted" : "Not mounted";color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
                    RowLayout {
                        Layout.fillWidth:true
                        OrbitButton {objectName:"deviceOpen_"+modelData.id;visible:modelData.mounted;text:"Open";Layout.fillWidth:true;enabled:!panel.data.busy;onClicked:DesktopTools.deviceAction(modelData.id,"open")}
                        OrbitButton {objectName:"deviceMount_"+modelData.id;visible:!modelData.mounted && modelData.canMount;text:"Mount";Layout.fillWidth:true;enabled:!panel.data.busy;onClicked:DesktopTools.deviceAction(modelData.id,"mount")}
                        OrbitButton {objectName:"deviceEject_"+modelData.id;visible:modelData.canEject || modelData.canUnmount;text:modelData.canEject ? "Eject" : "Unmount";Layout.fillWidth:true;enabled:!panel.data.busy;onClicked:DesktopTools.deviceAction(modelData.id,modelData.canEject ? "eject" : "unmount")}
                    }
                }
            }
            Text {visible:typeof DesktopTools.devices==="undefined" || !DesktopTools.devices.length;Layout.fillWidth:true;text:panel.data.gioAvailable ? "No removable devices found." : "Device integration requires GIO support.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
            OrbitButton {text:"Open Files";Layout.fillWidth:true;onClicked:DesktopTools.open("files")}
            Text {Layout.fillWidth:true;text:"For an encrypted drive or a password prompt, open Files. Its installed volume service handles unlocking.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
        }
        ColumnLayout {
            visible:panel.section==="tools";Layout.fillWidth:true;spacing:8
            Text {Layout.fillWidth:true;text:"System tools";color:Theme.text;font.pixelSize:Theme.fontSize(14)}
            Repeater {
                model:typeof DesktopTools.toolRows!=="undefined" ? DesktopTools.toolRows : Object.keys(DesktopTools.tools).filter(key=>["devices","defaults-mint","keyboard","screen-reader","input-method"].indexOf(key)<0).map(key=>({id:key,label:DesktopTools.tools[key].label,available:DesktopTools.tools[key].available,reason:"No compatible system tools are installed. Install the tool through your distribution’s package manager."}))
                delegate:ColumnLayout {
                    required property var modelData
                    Layout.fillWidth:true;spacing:3
                    OrbitButton {objectName:"systemTool_"+modelData.id;Layout.fillWidth:true;text:modelData.label;enabled:modelData.available;onClicked:DesktopTools.open(modelData.id)}
                    Text {visible:!modelData.available;Layout.fillWidth:true;text:modelData.reason || "Not installed";color:Theme.muted;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap;textFormat:Text.PlainText}
                }
            }
        }
    }
}
