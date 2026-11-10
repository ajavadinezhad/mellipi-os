import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: panel;objectName: "bluetoothPanel"
    property string forgetPath: ""
    readonly property bool codeEntry: Bluetooth.pairing.mode === "pin" || Bluetooth.pairing.mode === "passkey"
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    Connections {
        target: Bluetooth
        function onChanged() {
            if((Bluetooth.pairing.mode || "")!==code.mode || (Bluetooth.pairing.path || "")!==code.devicePath) {
                code.text="";code.mode=Bluetooth.pairing.mode || "";code.devicePath=Bluetooth.pairing.path || "";
            }
        }
    }
    ColumnLayout {id: content;width: panel.availableWidth;spacing: 10
    SettingsGroup {
        SettingRow {
            label: "Bluetooth"
            SettingToggle { label: "Bluetooth power";checked: Bluetooth.state.powered;enabled: Bluetooth.state.available && !Bluetooth.state.busy;onClicked: Bluetooth.setPowered(checked) }
        }
        SettingRow {
            label: Bluetooth.state.discovering ? "Searching nearby…" : "Nearby devices"
            OrbitButton { text: Bluetooth.state.discovering ? "Stop" : "Search";quiet: true;implicitHeight: 28;enabled: Bluetooth.state.available && Bluetooth.state.powered;onClicked: {if(Bluetooth.state.discovering)Bluetooth.stopDiscovery();else Bluetooth.startDiscovery();} }
        }
    }
    Text { visible: !Bluetooth.state.available || !Bluetooth.state.powered;text: Bluetooth.state.status || (Bluetooth.state.available ? "Turn Bluetooth on to connect devices" : "No Bluetooth adapter available");color: Theme.muted;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap;Layout.fillWidth: true;textFormat: Text.PlainText }
    SettingsGroup {
        visible: Bluetooth.pairing.mode !== undefined && Bluetooth.pairing.mode !== "";title: "Pairing"
        ColumnLayout {
            Layout.fillWidth: true;Layout.margins: 6;spacing: 8
            Text { text: Bluetooth.pairing.name || "Device";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true;elide: Text.ElideRight;textFormat: Text.PlainText }
            Text { visible: !panel.codeEntry;text: Bluetooth.pairing.passkey || "Confirm this connection";color: Theme.text;font.pixelSize: Theme.fontSize(20);font.letterSpacing: 3;Layout.fillWidth: true;textFormat: Text.PlainText }
            Text { text: panel.codeEntry ? (Bluetooth.pairing.mode==="pin" ? "Enter the PIN supplied with your device." : "Enter the numeric passkey shown on your device.") : Bluetooth.pairing.mode === "display" ? "Enter this code on your device." : "Confirm only if this request matches your device.";color: Theme.muted;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap;Layout.fillWidth: true }
            OrbitField {
                id: code;objectName: "bluetoothPairingCode";visible: panel.codeEntry;Layout.fillWidth: true
                property string mode: ""
                property string devicePath: ""
                onVisibleChanged: if(visible)Qt.callLater(function(){if(code.visible)code.forceActiveFocus();})
                Component.onCompleted: {mode=Bluetooth.pairing.mode || "";devicePath=Bluetooth.pairing.path || "";if(visible)Qt.callLater(function(){if(code.visible)code.forceActiveFocus();});}
                maximumLength: Bluetooth.pairing.mode==="passkey" ? 6 : 16
                Accessible.name: Bluetooth.pairing.mode==="passkey" ? "Bluetooth numeric passkey" : "Bluetooth PIN"
                placeholderText: Bluetooth.pairing.mode==="passkey" ? "Numeric passkey" : "Device PIN"
                inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhSensitiveData | (Bluetooth.pairing.mode==="passkey" ? Qt.ImhDigitsOnly : Qt.ImhNone)
                function submit(){if(Bluetooth.pairing.mode==="pin")Bluetooth.submitPinCode(text);else Bluetooth.submitPasskey(text);text="";}
                onAccepted: if(text.length>0)submit()
            }
            Text {objectName: "bluetoothPairingError";visible: text.length>0;text: Bluetooth.pairing.error || "";color: Theme.text;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap;Layout.fillWidth: true;textFormat: Text.PlainText}
            RowLayout {
                OrbitButton {objectName: "bluetoothPairingSubmit";visible: panel.codeEntry;text: "Pair";enabled: code.text.length>0;onClicked: code.submit()}
                OrbitButton { visible: !panel.codeEntry && Bluetooth.pairing.mode !== "display";text: "Confirm";onClicked: Bluetooth.answerPairing(true) }
                OrbitButton { text: "Cancel";quiet: true;onClicked: Bluetooth.cancelPairing() }
            }
        }
    }
    ListView {
        id: devices;Layout.fillWidth: true;Layout.preferredHeight: Math.max(44,Math.min(count,4)*62);clip: true;spacing: 4;reuseItems: true;model: Bluetooth.devices
        delegate: Rectangle {
            required property var modelData;width: devices.width;height: 58;radius: Theme.corner(7);color: Theme.surface
            Column {
                x: 10;anchors.verticalCenter: parent.verticalCenter;width: parent.width-160;spacing: 4
                Text { width: parent.width;text: modelData.name;color: Theme.text;font.pixelSize: Theme.fontSize(12);elide: Text.ElideRight;textFormat: Text.PlainText }
                Text { text: (modelData.connected ? "Connected" : modelData.paired ? "Paired" : "Available")+(modelData.batteryPresent ? " · "+modelData.batteryPercent+"%" : "");color: Theme.muted;font.pixelSize: Theme.fontSize(10) }
            }
            Row {
                anchors.right: parent.right;anchors.rightMargin: 6;anchors.verticalCenter: parent.verticalCenter;spacing: 2
                OrbitButton { text: modelData.connected ? "Disconnect" : modelData.paired ? "Connect" : "Pair";quiet: true;implicitHeight: 28;enabled: Bluetooth.state.powered && !Bluetooth.state.busy;onClicked: {if(modelData.connected)Bluetooth.disconnectDevice(modelData.path);else if(modelData.paired)Bluetooth.connectDevice(modelData.path);else Bluetooth.pairDevice(modelData.path);} }
                OrbitButton { visible: modelData.paired;text: "×";hint: "Forget device";quiet: true;implicitWidth: 26;implicitHeight: 28;enabled: !Bluetooth.state.busy;onClicked: panel.forgetPath=modelData.path }
            }
        }
        Text { anchors.centerIn: parent;visible: devices.count===0 && Bluetooth.state.powered;text: Bluetooth.state.discovering ? "Searching…" : "Search to find nearby devices";color: Theme.muted;font.pixelSize: Theme.fontSize(11) }
    }
    ColumnLayout {
        Layout.fillWidth:true;visible:Orbit.apps.some(a=>a.id==="blueman-manager.desktop");spacing:3
        OrbitButton {objectName:"advancedBluetoothManager";text:"Advanced device manager…";quiet:true;implicitHeight:28;onClicked:Orbit.launch("blueman-manager.desktop")}
        Text {Layout.fillWidth:true;text:"Open Blueman for device services and troubleshooting.";color:Theme.faint;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap}
    }
    RowLayout {
        visible: panel.forgetPath!=="";Layout.fillWidth: true
        OrbitButton { text: "Forget device";onClicked: {Bluetooth.forgetDevice(panel.forgetPath);panel.forgetPath="";} }
        OrbitButton { text: "Cancel";quiet: true;onClicked: panel.forgetPath="" }
    }
    }
}
