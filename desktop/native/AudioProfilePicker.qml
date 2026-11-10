import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: profiles;objectName: "audioProfilePicker";Layout.fillWidth: true;spacing: 5
    property var cards: System.values.audioCards || []
    property string selectedCard: ""
    property bool cardExpanded: false
    property bool profileExpanded: false
    signal opening()
    function collapse(){cardExpanded=false;profileExpanded=false;}
    readonly property var card: {
        for(var i=0;i<cards.length;i++)if(cards[i].name===selectedCard)return cards[i];
        return cards.length ? cards[0] : null;
    }
    AudioDevicePicker {
        objectName: "audioCardPicker";accessibleLabel: "Sound card"
        devices: profiles.cards;selectedName: profiles.card ? profiles.card.name : "";emptyLabel: "No audio devices"
        expanded: profiles.cardExpanded
        onToggled: {profiles.opening();profiles.cardExpanded=!profiles.cardExpanded;profiles.profileExpanded=false;}
        onSelected: name => {profiles.selectedCard=name;profiles.cardExpanded=false;profiles.profileExpanded=false;}
    }
    AudioDevicePicker {
        objectName: "audioCardProfilePicker";accessibleLabel: "Audio profile"
        devices: profiles.card ? profiles.card.profiles : [];selectedName: profiles.card ? profiles.card.activeProfile : ""
        emptyLabel: "No profiles available";expanded: profiles.profileExpanded
        onToggled: {profiles.opening();profiles.profileExpanded=!profiles.profileExpanded;profiles.cardExpanded=false;}
        onSelected: name => {profiles.profileExpanded=false;if(profiles.card)System.setAudioProfile(profiles.card.name,name);}
    }
    Text {
        Layout.fillWidth: true;Layout.leftMargin: 6;Layout.rightMargin: 6
        text: profiles.card && profiles.card.activeProfile==="off" ? "This device is off. Choose an input, output or duplex profile to enable it." : "Profiles control which inputs and outputs this device exposes. Not connected profiles can be selected to recover a disabled jack."
        color: Theme.muted;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap;textFormat: Text.PlainText
    }
}
