import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
SettingsGroup {
                id:sound
                property bool showDeviceLink: true
                property bool showDevicePicker: false
                property bool devicePickerExpanded: false
                signal devicePickerToggled()
                signal devicePickerSelected()
                title: "Sound"
                Loader {
                    objectName:"outputDevicePickerLoader";Layout.fillWidth:true;active:sound.showDevicePicker;visible:active
                    sourceComponent:Component {AudioDevicePicker {
                        objectName:"outputDevicePicker";accessibleLabel:"Output device";devices:System.values.audioOutputs || []
                        selectedName:System.values.defaultOutput || "";emptyLabel:"No output device";expanded:sound.devicePickerExpanded
                        onToggled:sound.devicePickerToggled()
                        onSelected:name=>{System.setOutputDevice(name);sound.devicePickerSelected();}
                    }}
                }
                SettingRow {
                    label: showDevicePicker ? "Volume" : System.values.audioAvailable ? System.values.audioName : "Unavailable"
                    Text { text: System.values.audioAvailable ? Math.round(volume.value)+"%" : "";color: Theme.muted;font.pixelSize: Theme.fontSize(11) }
                    IconButton { objectName: "soundMuteButton";iconName: System.values.muted ? "mute" : "volume";hint: System.values.muted ? "Unmute" : "Mute";enabled: System.values.audioAvailable;onClicked: System.toggleMute() }
                }
                OrbitSlider {
                    id: volume;property bool userAdjusting: false
                    Accessible.name: "Output volume"
                    Layout.fillWidth: true;Layout.leftMargin: 6;Layout.rightMargin: 6
                    from: 0;to: 100;stepSize: 1;value: System.values.volume;enabled: System.values.audioAvailable
                    onMoved: {userAdjusting=true;volumeTimer.restart();}
                    onPressedChanged: if(!pressed && userAdjusting){volumeTimer.stop();System.setVolume(Math.round(value));userAdjusting=false;}
                    Timer { id: volumeTimer;interval: 120;onTriggered: {System.setVolume(Math.round(volume.value));if(!volume.pressed)volume.userAdjusting=false;} }
                }
                OrbitButton {
                    objectName: "audioDevicesLink";visible: showDeviceLink
                    text: "Audio devices & microphone…";quiet: true;implicitHeight: 26
                    Layout.fillWidth: true
                    onClicked: Orbit.openSettingsSection(8)
                }
            }
