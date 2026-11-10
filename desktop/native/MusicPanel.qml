import QtQuick 2.15
import QtQuick.Layouts 1.15
import QtQuick.Controls 2.15
import "."
ScrollView {
    id: music;objectName: "musicPanel"
    property bool showPlayback: true
    property bool compactControls: false
    property string expandedDevice: ""
    property bool showProfiles: false
    onExpandedDeviceChanged: if(expandedDevice!=="" && detailsLoader.item)detailsLoader.item.collapseProfiles()
    onShowProfilesChanged: if(!showProfiles && detailsLoader.item)detailsLoader.item.collapseProfiles()
    onCompactControlsChanged: {expandedDevice="";showProfiles=false;}
    contentWidth: availableWidth;implicitHeight: content.implicitHeight;clip: true
    ColumnLayout {id: content;width: music.availableWidth;spacing: 10
            SettingsGroup {
                title: "Now playing";visible: music.showPlayback
                RowLayout {
                    Layout.fillWidth: true;Layout.margins: 5;spacing: 6
                    ColumnLayout {
                        Layout.fillWidth: true;spacing: 3
                        Text { text: Media.state.available ? (Media.state.title || "Media playback") : "Nothing playing";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true;elide: Text.ElideRight;textFormat: Text.PlainText }
                        Text { text: Media.state.artist || "";visible: text.length>0;color: Theme.faint;font.pixelSize: Theme.fontSize(10);Layout.fillWidth: true;elide: Text.ElideRight;textFormat: Text.PlainText }
                    }
                    IconButton { objectName: "mediaPreviousButton";iconName: "previous";hint: "Previous track";enabled: Media.state.available && Media.state.canPrevious;onClicked: Media.previous() }
                    IconButton { objectName: "mediaPlayButton";iconName: Media.state.playing ? "pause" : "play";hint: Media.state.playing ? "Pause" : "Play";enabled: Media.state.available && (Media.state.playing ? Media.state.canPause : Media.state.canPlay);onClicked: Media.playPause() }
                    IconButton { objectName: "mediaNextButton";iconName: "next";hint: "Next track";enabled: Media.state.available && Media.state.canNext;onClicked: Media.next() }
                }
            }
    OrbitButton {
        visible: music.compactControls;objectName: "soundSettingsLink";text: "Sound settings…"
        Layout.fillWidth: true;quiet: true;implicitHeight: 28
        onClicked: Orbit.openSettingsSection(8)
    }
    SoundControls {
        title: "Output";showDeviceLink: false;showDevicePicker: !music.compactControls
        devicePickerExpanded: music.expandedDevice==="output"
        onDevicePickerToggled: music.expandedDevice=devicePickerExpanded ? "" : "output"
        onDevicePickerSelected: music.expandedDevice=""
    }
    Loader {
        id: detailsLoader;objectName:"audioDetailsLoader";Layout.fillWidth:true
        active: !music.compactControls;visible:active
        sourceComponent: Component {AudioDetails {owner:music}}
    }

}

}
