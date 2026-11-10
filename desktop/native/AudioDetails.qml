import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id:details;objectName:"audioDetailsPanel"
    property var owner
    spacing:10
    function collapseProfiles(){if(profilesLoader.item)profilesLoader.item.collapse();}
    SettingsGroup {
        title: "Microphone"
        AudioDevicePicker {
            objectName: "inputDevicePicker";accessibleLabel: "Microphone";devices: System.values.audioInputs || []
            selectedName: System.values.defaultInput || "";emptyLabel: "No microphone"
            expanded: details.owner.expandedDevice==="input"
            onToggled: details.owner.expandedDevice=expanded ? "" : "input"
            onSelected: name => {details.owner.expandedDevice="";System.setInputDevice(name);}
        }
        Text {
            objectName: "microphoneStatus";text: System.values.inputReason || "";visible: text.length>0
            Layout.fillWidth: true;Layout.margins: 6;color: Theme.muted;font.pixelSize: Theme.fontSize(10)
            wrapMode: Text.Wrap;textFormat: Text.PlainText
        }
        SettingRow {
            label: "Input level"
            Text {text: !!System.values.inputAvailable ? Math.round(microphone.value)+"%" : "Unavailable";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
            IconButton {
                objectName: "inputMuteButton";iconName: !!System.values.inputMuted ? "microphone-mute" : "microphone"
                hint: !!System.values.inputMuted ? "Unmute microphone" : "Mute microphone"
                enabled: !!System.values.inputAvailable;onClicked: System.toggleInputMute()
            }
        }
        OrbitSlider {
            id: microphone;objectName: "inputVolumeSlider";property bool userAdjusting: false
            Accessible.name: "Microphone input level"
            Layout.fillWidth: true;Layout.leftMargin: 6;Layout.rightMargin: 6
            from: 0;to: 100;stepSize: 1;value: System.values.inputVolume || 0;enabled: !!System.values.inputAvailable
            onMoved: {userAdjusting=true;inputTimer.restart();}
            onPressedChanged: if(!pressed && userAdjusting){inputTimer.stop();System.setInputVolume(Math.round(value));userAdjusting=false;}
            Timer {id: inputTimer;interval: 120;onTriggered: {System.setInputVolume(Math.round(microphone.value));if(!microphone.pressed)microphone.userAdjusting=false;}}
        }
    }
    OrbitButton {
        objectName: "audioProfilesToggle";text: details.owner.showProfiles ? "Hide device profiles" : "Device profiles…"
        Layout.fillWidth: true;implicitHeight: 28;quiet: true
        onClicked: {details.owner.showProfiles=!details.owner.showProfiles;details.owner.expandedDevice="";if(details.owner.showProfiles)System.refreshAudioProfiles();}
    }
    SettingsGroup {
        title: "Device profiles";visible: details.owner.showProfiles
        Loader {id: profilesLoader;objectName:"audioProfileDetailsLoader";Layout.fillWidth:true;active:details.owner.showProfiles;sourceComponent:Component{AudioProfilePicker{onOpening:details.owner.expandedDevice=""}}}
    }
}
