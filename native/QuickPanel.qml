import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: quick;objectName: "quickPanel"
    property int section: typeof Orbit.quickSection!=="undefined" ? Orbit.quickSection : 0
    property alias displayOptions: brightnessControls.displayOptions
    property string selectedSsid: ""
    property bool contentReady: false
    readonly property bool wifiBusy: !!System.values.wifiConnecting
    readonly property bool wifiScanning: !!System.values.wifiScanning
    function connectSelectedNetwork() {
        if(!selectedSsid || wifiBusy)return;
        System.connectWifi(selectedSsid,wifiPassword.text);wifiPassword.text="";selectedSsid="";
    }
    function animateTab() {
        if(!contentReady)return;
        tabFade.stop();content.opacity=1;
        if(!Theme.reducedMotion)tabFade.start();
    }
    Component.onCompleted: contentReady=true
    NumberAnimation {
        id:tabFade;objectName:"quickTabFade";target:content;property:"opacity"
        from:0.76;to:1;duration:Theme.economy ? 80 : 130;easing.type:Easing.OutCubic
    }
    readonly property bool motionDisabled:Theme.reducedMotion
    onMotionDisabledChanged:if(motionDisabled){tabFade.stop();content.opacity=1;}
    spacing: 10
    implicitHeight: tabs.implicitHeight+content.implicitHeight+settingsLink.implicitHeight+spacing*3
    onSectionChanged: {
        animateTab();
        selectedSsid="";displayOptions=false;sessionActions.confirmSleep=false;
        if(wifiPassword)wifiPassword.text="";
        if(section===1 && System.values.wifiEnabled)System.refreshWifi();
    }
        SettingsSegments {
            id: tabs;
            Layout.fillWidth: true;segmentWidth: Math.floor((quick.width-6)/3)
            value: quick.section;options: [{label:"Controls",value:0,glyph:"controls"},{label:"Connections",value:1,glyph:"connections"},{label:"Power",value:2,glyph:"power"}]
            onSelected: value => quick.section=value
        }
    ScrollView {
        id: body;objectName: "quickScrollBody"
        Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 0
        clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            id: content;width: body.availableWidth;spacing: 10
        ColumnLayout {
            visible: quick.section===0;Layout.fillWidth: true;spacing: 10
            SoundControls {
                objectName: "quickSoundControls"
                showDeviceLink: true
            }
            BrightnessPanel {id: brightnessControls;showDisplayOptions:false}
        }
        ColumnLayout {
            visible: quick.section===1;Layout.fillWidth: true;spacing: 10
            SettingsGroup {
                title: "Wi-Fi"
                SettingRow {
                    label: System.values.networkAvailable ? System.values.networkState : "Unavailable"
                    OrbitButton { text: "↻";quiet: true;implicitWidth: 26;implicitHeight: 26;hint: "Refresh networks";enabled: System.values.networkAvailable && System.values.wifiEnabled && !quick.wifiBusy && !quick.wifiScanning;onClicked: System.refreshWifi() }
                    SettingToggle { label: "Wi-Fi power";checked: System.values.wifiEnabled;enabled: System.values.networkAvailable && !quick.wifiBusy;onClicked: System.setWifi(checked) }
                }
                ListView {
                    id: networks;visible: System.values.wifiEnabled && count>0
                    Layout.fillWidth: true;Layout.preferredHeight: Math.min(count,4)*36;clip: true;model: System.values.wifiNetworks;reuseItems: true
                    delegate: Rectangle {
                        objectName: "wifiNetwork_"+modelData.ssid
                        required property var modelData
                        enabled: !quick.wifiBusy
                        activeFocusOnTab: true
                        function selectNetwork(){if(quick.wifiBusy)return;quick.selectedSsid=modelData.ssid;wifiPassword.text="";wifiPassword.forceActiveFocus();}
                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.ssid
                        Accessible.description: (modelData.active ? "Connected · " : "")+(modelData.secure ? "Secured" : "Open network")+" · "+modelData.signal+"%"
                        Accessible.onPressAction: selectNetwork()
                        Keys.onReturnPressed: selectNetwork()
                        Keys.onEnterPressed: selectNetwork()
                        Keys.onSpacePressed: selectNetwork()
                        border.color: activeFocus ? Theme.focusColor : "transparent"
                        width: networks.width;height: 34;radius: Theme.corner(6)
                        color: wifiHit.containsMouse || quick.selectedSsid===modelData.ssid ? Theme.hover : "transparent"
                        RowLayout {
                            anchors.fill: parent;anchors.leftMargin: 8;anchors.rightMargin: 8
                            Text { text: modelData.ssid;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.text;font.pixelSize: Theme.fontSize(11);textFormat: Text.PlainText }
                            Text { text: modelData.active ? "✓" : (modelData.secure ? "⌑ " : "")+modelData.signal+"%";color: Theme.muted;font.pixelSize: Theme.fontSize(10) }
                        }
                        MouseArea { id: wifiHit;anchors.fill: parent;hoverEnabled: true;onClicked: parent.selectNetwork() }
                    }
                }
                Text {
                    objectName: "wifiProgress";Layout.fillWidth: true;Layout.margins: 6
                    visible: quick.wifiBusy || quick.wifiScanning
                    text: quick.wifiBusy ? "Connecting to "+(System.values.wifiTarget || "network")+"…" : "Searching for networks…"
                    color: Theme.muted;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap;textFormat: Text.PlainText
                }
                Text {
                    objectName: "wifiError";Layout.fillWidth: true;Layout.margins: 6
                    visible: !!System.values.wifiError;text: System.values.wifiError || ""
                    color: Theme.muted;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap;textFormat: Text.PlainText
                }
                Text {
                    visible: System.values.wifiEnabled && !quick.wifiBusy && !quick.wifiScanning && networks.count===0 && !System.values.wifiError
                    text: "No nearby networks. Try Refresh.";Layout.fillWidth: true;Layout.margins: 6
                    color: Theme.muted;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap
                }
                ColumnLayout {
                    enabled: !quick.wifiBusy
                    visible: quick.selectedSsid!=="";Layout.fillWidth: true;Layout.margins: 4;spacing: 4
                    Text { text: "Connect to "+quick.selectedSsid;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.muted;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText }
                    RowLayout {
                        Layout.fillWidth: true
                        OrbitField { id: wifiPassword;objectName: "wifiPassword";placeholderText: "Password, if required";echoMode: TextInput.Password;Layout.fillWidth: true;implicitHeight: 30;onAccepted:quick.connectSelectedNetwork() }
                        OrbitButton { text: "Connect";implicitHeight: 28;onClicked: quick.connectSelectedNetwork() }
                    }
                }
            }
            OrbitButton {objectName:"quickConnectionsLink";text:"Connection settings…";quiet:true;Layout.fillWidth:true;implicitHeight:26;onClicked:Orbit.openSettingsSection(5)}
            SettingsGroup {
                title: "Bluetooth"
                SettingRow {
                    label: Bluetooth.state.available ? (Bluetooth.state.powered ? "On" : "Off") : "Unavailable"
                    OrbitButton { text: "Devices…";quiet: true;implicitHeight: 26;enabled: Bluetooth.state.available;onClicked: Orbit.showPanel("bluetooth") }
                    SettingToggle { label: "Bluetooth power";checked: Bluetooth.state.powered;enabled: Bluetooth.state.available && !Bluetooth.state.busy;onClicked: Bluetooth.setPowered(checked) }
                }
                Repeater {
                    model: Bluetooth.devices.filter(d => d.connected && d.batteryPresent).slice(0,3)
                    SettingRow { required property var modelData;label: modelData.name;Text { text: modelData.batteryPercent+"%";color: Theme.muted;font.pixelSize: Theme.fontSize(11) } }
                }
            }
        }
        ColumnLayout {
            visible: quick.section===2;Layout.fillWidth: true;spacing: 10
            SessionPanel {id: sessionActions;Layout.fillWidth: true}
            SettingsGroup {
                title: "Battery"
                SettingRow {
                    label: Power.state.percentageAvailable ? Power.state.batteryPercent+"%"+(Power.state.charging ? " · Charging" : "") : System.values.batteryPresent ? System.values.batteryPercent+"%" : Power.state.batteryPresent ? "Battery level unavailable" : "No system battery"
                    OrbitButton {text: "Health…";quiet: true;implicitHeight: 26;onClicked: Orbit.showPanel("battery")}
                }
            }
        }
        }
    }
    RowLayout {
        id:settingsLink;Layout.fillWidth:true;spacing:6
        OrbitButton {objectName:"systemSettingsLink";text:"System settings…";quiet:true;implicitHeight:28;Layout.fillWidth:true;onClicked:Orbit.showPanel("system-settings")}
        IconButton {
            objectName:"quickUpdates";iconName:"refresh";implicitWidth:28;implicitHeight:28
            readonly property bool available:typeof DesktopTools!=="undefined" && DesktopTools!==null && !!DesktopTools.tools.updates && DesktopTools.tools.updates.available
            enabled:available;hint:available ? "Software updates" : "Install a software update manager to check for updates"
            onClicked:DesktopTools.open("updates")
        }
    }
}
