import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: quick;objectName: "quickPanel"
    property int section: typeof Orbit.quickSection!=="undefined" ? Orbit.quickSection : 0
    property string selectedSsid: ""
    property bool selectedSecure: false
    property bool submitted: false
    onWifiBusyChanged: if(!wifiBusy && submitted) {
        submitted=false;
        if(!System.values.wifiError) {selectedSsid="";wifiPassword.text="";}
    }
    property bool contentReady: false
    readonly property bool wifiBusy: !!System.values.wifiConnecting
    readonly property bool wifiScanning: !!System.values.wifiScanning
    function connectSelectedNetwork() {
        if(!selectedSsid || wifiBusy)return;
        submitted=true;
        System.connectWifi(selectedSsid,selectedSecure ? wifiPassword.text : "");
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
    readonly property int rowGap: Theme.extraCompact ? 6 : 9
    spacing: rowGap
    implicitHeight: tabs.implicitHeight+content.implicitHeight+settingsLink.implicitHeight+spacing*2
    onSectionChanged: {
        animateTab();
        selectedSsid="";sessionActions.confirmSleep=false;
        if(wifiPassword)wifiPassword.text="";
        if(body && body.contentItem)body.contentItem.contentY=0;
        if(section===1 && System.values.wifiEnabled)System.refreshWifi();
    }
        SettingsSegments {
            id: tabs;
            Layout.fillWidth: true;segmentWidth: 75
            value: quick.section;options: [{label:"Controls",value:0,glyph:"controls"},{label:"Connect",value:1,glyph:"connections"},{label:"Power",value:2,glyph:"power"}]
            onSelected: value => quick.section=value
        }
    ScrollView {
        id: body;objectName: "quickScrollBody"
        Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 0
        clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            id: content;width: body.availableWidth;spacing: quick.rowGap
        Rectangle {
            visible: quick.section===0;Layout.fillWidth: true
            implicitHeight: levels.implicitHeight+16
            radius: Theme.corner(12);color: Theme.surface
            border.color: Theme.controlBorder;border.width: Theme.surfaceOutline
            ColumnLayout {
                id: levels;x:8;y:8;width:Math.max(0,parent.width-16);spacing:quick.rowGap
                QuickLevel {
                    objectName:"quickSoundControls";title:"Volume";valueName:"Output volume"
                    value: System.values.volume || 0; available: !!System.values.audioAvailable
                    glyph: System.values.muted ? "mute" : "volume"
                    glyphActionLabel: System.values.muted ? "Unmute" : "Mute"
                    glyphObjectName:"soundMuteButton"
                    onGlyphActivated: System.toggleMute()
                    detailsHint: "Audio devices and microphone"
                    linkObjectName:"audioDevicesLink"
                    currentDevice: System.values.audioName || ""
                    onDetailsActivated: Orbit.openSettingsSection(8)
                    onApplied: value => System.setVolume(value)
                }
                Rectangle {Layout.fillWidth:true;implicitHeight:1;color:Theme.separator}
                QuickLevel {
                    title:"Brightness";valueName:"Display brightness";sliderObjectName:"brightnessSlider"
                    value: Brightness.state.percent || 0;minimum:1;available:!!Brightness.state.available
                    glyph:"display";currentDevice:Brightness.state.name || ""
                    unavailable:Brightness.state.reason || "Brightness controls unavailable"
                    detailsHint:"Brightness settings"
                    onDetailsActivated: Orbit.openSettingsSection(15)
                    onApplied: value => Brightness.setBrightness(value)
                }
            }
        }
        ColumnLayout {
            visible: quick.section===1;Layout.fillWidth: true;spacing: quick.rowGap
            SettingsGroup {
                title: "Wi-Fi"
                SettingRow {
                    label: System.values.networkAvailable ? System.values.networkState : "Unavailable"
                    IconButton {iconName: "refresh";implicitWidth: 26;implicitHeight: 26;hint: "Refresh Wi-Fi networks";enabled: System.values.networkAvailable && System.values.wifiEnabled && !quick.wifiBusy && !quick.wifiScanning;onClicked: System.refreshWifi()}
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
                        function selectNetwork(){if(quick.wifiBusy)return;quick.selectedSsid=modelData.active ? "" : modelData.ssid;quick.selectedSecure=modelData.secure;wifiPassword.text="";if(modelData.active)return;if(modelData.secure)wifiPassword.forceActiveFocus();else quick.connectSelectedNetwork();}
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
                            Text {text: modelData.active ? "Connected" : (modelData.secure ? "Secured · " : "")+modelData.signal+"%";color: Theme.muted;font.pixelSize: Theme.fontSize(10)}
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
                    text: "No nearby networks";Layout.fillWidth: true;Layout.margins: 6
                    color: Theme.muted;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap
                }
                ColumnLayout {
                    enabled: !quick.wifiBusy
                    visible: quick.selectedSsid!=="";Layout.fillWidth: true;Layout.margins: 4;spacing: 4
                    Text { text: "Connect to "+quick.selectedSsid;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.muted;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText }
                    RowLayout {
                        readonly property int fieldHeight:Math.max(30,Theme.fontSize(12)+16)
                        Layout.fillWidth: true
                        OrbitField { id: wifiPassword;visible: quick.selectedSecure;objectName: "wifiPassword";placeholderText: "Wi-Fi password";echoMode: TextInput.Password;Layout.fillWidth: true;Layout.minimumWidth:0;implicitHeight:parent.fieldHeight;onAccepted:quick.connectSelectedNetwork() }
                        OrbitButton { text: "Join";implicitHeight:parent.fieldHeight;accent:true;onClicked: quick.connectSelectedNetwork() }
                    }
                }
            }
            SettingsGroup {
                title: "Bluetooth"
                SettingRow {
                    label: Bluetooth.state.available ? (Bluetooth.state.powered ? "On" : "Off") : "Unavailable"
                    IconButton { iconName: "bluetooth";hint: "Bluetooth devices";enabled: Bluetooth.state.available;onClicked: Orbit.showPanel("bluetooth") }
                    SettingToggle { label: "Bluetooth power";checked: Bluetooth.state.powered;enabled: Bluetooth.state.available && !Bluetooth.state.busy;onClicked: Bluetooth.setPowered(checked) }
                }
                Repeater {
                    model: Bluetooth.devices.filter(d => d.connected && d.batteryPresent).slice(0,3)
                    SettingRow { required property var modelData;label: modelData.name;Text { text: modelData.batteryPercent+"%";color: Theme.muted;font.pixelSize: Theme.fontSize(11) } }
                }
            }
            OrbitButton {objectName:"quickConnectionsLink";text:"Network settings";quiet:true;Layout.fillWidth:true;implicitHeight:Math.max(28,Theme.fontSize(11)+12);onClicked:Orbit.openSettingsSection(5)}
        }
        ColumnLayout {
            visible: quick.section===2;Layout.fillWidth: true;spacing: quick.rowGap
            SessionPanel {id: sessionActions;Layout.fillWidth: true}
            SettingsGroup {
                title: "Battery"
                SettingRow {
                    label: Power.state.percentageAvailable ? Power.state.batteryPercent+"%"+(Power.state.charging ? " · Charging" : "") : System.values.batteryPresent ? System.values.batteryPercent+"%" : Power.state.batteryPresent ? "Battery level unavailable" : "No system battery"
                    IconButton {iconName: "battery";hint: "Battery health";onClicked: Orbit.showPanel("battery")}
                }
            }
        }
        }
    }
    RowLayout {
        id:settingsLink;Layout.fillWidth:true;spacing:6
        Item {Layout.fillWidth: true}
        IconButton {objectName:"systemSettingsLink";iconName:"settings";hint:"Open Settings";implicitHeight:28;onClicked:Orbit.showPanel("system-settings")}
        IconButton {
            objectName:"quickUpdates";iconName:"updates";implicitWidth:28;implicitHeight:28
            accessibleLabel:"Software updates"
            readonly property bool available:typeof DesktopTools!=="undefined" && DesktopTools!==null && !!DesktopTools.tools.updates && DesktopTools.tools.updates.available
            enabled:available;hint:available ? "Software updates" : "Install a software update manager to check for updates"
            onClicked:DesktopTools.open("updates")
        }
    }

    component QuickLevel: ColumnLayout {
        id: level
        required property string title
        required property string valueName
        required property string glyph
        property string glyphActionLabel: ""
        property string glyphObjectName: ""
        property string linkObjectName: ""
        property string sliderObjectName: ""
        property string detailsHint: ""
        property string currentDevice: ""
        property string unavailable: "Unavailable"
        property real value: 0
        property int minimum: 0
        property bool available: false
        signal glyphActivated()
        signal detailsActivated()
        signal applied(int value)
        Layout.fillWidth: true;Layout.minimumWidth: 0;spacing: 0
        RowLayout {
            Layout.fillWidth: true;spacing: 5
            Text {
                text: level.title;color: Theme.text;font.pixelSize:Theme.fontSize(12);font.weight:Font.DemiBold
                Layout.fillWidth:true;Layout.minimumWidth:0;elide:Text.ElideRight
            }
            Text {visible:level.available;text:Math.round(levelSlider.value)+"%";color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            IconButton {
                objectName:level.linkObjectName;iconName:"chevron-right"
                hint:level.currentDevice && level.currentDevice!==level.detailsHint ? level.detailsHint+": "+level.currentDevice : level.detailsHint
                accessibleLabel:level.detailsHint;onClicked:level.detailsActivated()
            }
        }
        RowLayout {
            visible:level.available;Layout.fillWidth:true;spacing:6
            IconButton {
                visible:level.glyphActionLabel.length>0;objectName:level.glyphObjectName
                iconName:level.glyph;hint:level.glyphActionLabel;onClicked:level.glyphActivated()
            }
            Image {
                visible:level.glyphActionLabel.length===0;Layout.preferredWidth:18;Layout.preferredHeight:18
                Layout.leftMargin:6;Layout.rightMargin:6
                sourceSize:Qt.size(24,24);source:Theme.symbolicIconSource(level.glyph,Theme.accentInk)
            }
            OrbitSlider {
                id:levelSlider;objectName:level.sliderObjectName;property bool userAdjusting:false
                Accessible.name:level.valueName;Layout.fillWidth:true;Layout.minimumWidth:0
                from:level.minimum;to:100;stepSize:1;value:level.value;enabled:level.available
                onMoved:{userAdjusting=true;levelTimer.restart();}
                onPressedChanged:if(!pressed && userAdjusting){levelTimer.stop();level.applied(Math.round(value));userAdjusting=false;}
                Timer {id:levelTimer;interval:120;onTriggered:{level.applied(Math.round(levelSlider.value));if(!levelSlider.pressed)levelSlider.userAdjusting=false;}}
            }
        }
        Text {
            visible:!level.available;Layout.fillWidth:true;text:level.unavailable;textFormat:Text.PlainText
            color:Theme.muted;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap
        }
    }
}
