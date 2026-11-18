import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import "."
import "SettingReveal.js" as SettingReveal
ColumnLayout {
    id: quick;objectName: "quickPanel"
    property int section: typeof Orbit.quickSection!=="undefined" ? Orbit.quickSection : 0
    property string selectedSsid: ""
    property bool selectedSecure: false
    property bool submitted: false
    property Item selectedNetworkItem: null
    property Item returnFocus: null
    property string audioPicker: ""
    readonly property var defaultOrder: ["volume","brightness","connections","power"]
    readonly property var controlOrder: (Orbit.appearance || {}).quickControlOrder || defaultOrder
    readonly property var controlNames: ({volume:"Volume",brightness:"Brightness",connections:"Connections",power:"Power"})
    property bool arranging: false
    property string liftedControl: ""
    property point dragPoint
    property string refocusControl: ""
    readonly property var insertion: liftedControl ? insertionAt(dragPoint,body.contentItem.contentY,body.height) : null
    function dropCandidate(key,after,y) {
        const order=controlOrder;
        const from=order.indexOf(liftedControl),anchor=order.indexOf(key);
        const to=anchor+(after ? 1 : 0)-(from<anchor ? 1 : 0);
        return from===to ? null : {key:key,after:after,y:y};
    }
    function insertionAt(point, scrollY, viewportHeight) {
        const local=body.mapFromItem(null,point.x,point.y);
        if(local.x<0 || local.x>=body.width || local.y<0 || local.y>=viewportHeight)return null;
        const onContent=content.mapFromItem(null,point.x,point.y);
        for(let i=0;i<quickRows.count;i++){
            const row=quickRows.itemAt(i);
            if(row && row.visible && row.modelData!==liftedControl && onContent.y<=row.y+row.height/2)
                return dropCandidate(row.modelData,false,row.y);
        }
        for(let i=quickRows.count-1;i>=0;i--){
            const row=quickRows.itemAt(i);
            if(row && row.visible && row.modelData!==liftedControl)
                return dropCandidate(row.modelData,true,row.y+row.height);
        }
        return null;
    }
    function completeReorder(point) {
        if(!liftedControl)return;
        const key=liftedControl;
        const target=insertionAt(point,body.contentItem.contentY,body.height);
        liftedControl="";
        if(target){
            const row=quickRows.itemAt(controlOrder.indexOf(key));
            if(row && row.grip.activeFocus)refocusControl=key;
            Orbit.dropQuickControl(key,target.key,target.after);
        }
    }
    onControlOrderChanged: if(refocusControl)Qt.callLater(function(){
        const row=quickRows.itemAt(quick.controlOrder.indexOf(quick.refocusControl));
        quick.refocusControl="";
        if(row && row.visible && quick.section===0)row.grip.forceActiveFocus(Qt.TabFocusReason);
    })
    Timer {
        interval:32;repeat:true;running:!!quick.liftedControl
        onTriggered:{
            const y=body.mapFromItem(null,quick.dragPoint.x,quick.dragPoint.y).y;
            const x=body.mapFromItem(null,quick.dragPoint.x,quick.dragPoint.y).x;
            if(x<0 || x>=body.width || y<0 || y>=body.height)return;
            const step=y<20 ? -9 : y>body.height-20 ? 9 : 0;
            const flick=body.contentItem;
            if(step)flick.contentY=Math.max(0,Math.min(flick.contentY+step,Math.max(0,flick.contentHeight-flick.height)));
        }
    }
    readonly property string batteryStatus: Power.state.percentageAvailable
        ? Power.state.batteryPercent+"%"+(Power.state.charging ? " · Charging" : "")
        : System.values.batteryPresent ? System.values.batteryPercent+"%" : ""
    function openDetails(next, source) {
        returnFocus=source;
        section=next;
        Qt.callLater(function(){if(detailBack.visible)detailBack.forceActiveFocus(Qt.TabFocusReason);});
    }
    function setArranging(value) {
        arranging=value;
        if(value)Qt.callLater(function(){
            const row=quickRows.itemAt(0);
            if(quick.arranging && row && row.grip.visible)row.grip.forceActiveFocus();
        });
        else arrangeButton.forceActiveFocus(Qt.TabFocusReason);
    }
    function showOverview() {
        section=0;
        Qt.callLater(function(){if(returnFocus && returnFocus.visible) returnFocus.forceActiveFocus(Qt.TabFocusReason);});
    }
    Keys.onEscapePressed: event => {
        event.accepted=!!quick.liftedControl || quick.arranging || quick.section!==0;
        if(quick.liftedControl)quick.liftedControl="";
        else if(quick.arranging)quick.setArranging(false);
        else if(quick.section===1 && quick.selectedSsid && !quick.wifiBusy)quick.cancelNetwork();
        else if(event.accepted)quick.showOverview();
    }
    function reveal(item) {
        SettingReveal.scrollTo(body,item,4);
    }
    Connections {
        target:quick.Window.window
        function onActiveFocusItemChanged() {
            Qt.callLater(function(){var window=quick.Window.window;if(window)quick.reveal(window.activeFocusItem);});
        }
    }
    onWifiBusyChanged: if(!wifiBusy && submitted) {
        submitted=false;
        if(!System.values.wifiError) {selectedSsid="";wifiPassword.text="";}
    }
    property bool contentReady: false
    readonly property bool wifiBusy: !!System.values.wifiConnecting
    readonly property bool wifiScanning: !!System.values.wifiScanning
    function cancelNetwork() {
        if(wifiBusy)return;
        const row=selectedNetworkItem;
        selectedNetworkItem=null;
        selectedSsid="";
        wifiPassword.text="";
        Qt.callLater(function(){
            if(quick.section!==1)return;
            if(row && row.visible)row.forceActiveFocus(Qt.TabFocusReason);
            else detailBack.forceActiveFocus(Qt.TabFocusReason);
        });
    }
    function chooseNetwork(row, item) {
        if(wifiBusy)return;
        selectedNetworkItem=item;
        selectedSsid=row.active ? "" : row.ssid;
        selectedSecure=row.secure;
        wifiPassword.text="";
        if(row.active)return;
        if(!row.secure){connectSelectedNetwork();return;}
        // Keep the join controls visible even when the selected row was
        // reached inside a scrolled list on a short screen.
        if(body.contentItem)body.contentItem.contentY=0;
        wifiPassword.forceActiveFocus();
    }
    function connectSelectedNetwork() {
        if(!selectedSsid || wifiBusy)return;
        submitted=true;
        System.connectWifi(selectedSsid,selectedSecure ? wifiPassword.text : "");
    }
    function animateTab() {
        if(!contentReady)return;
        tabFade.stop();content.opacity=1;
        if(Theme.panelMotionEnabled)tabFade.start();
    }
    Component.onCompleted: {
        contentReady=true;
        if(typeof Orbit.quickArrangeRequested!=="undefined" && Orbit.quickArrangeRequested===true)setArranging(true);
    }
    NumberAnimation {
        id:tabFade;objectName:"quickTabFade";target:content;property:"opacity"
        from:0.76;to:1;duration:Theme.motionDuration(130,80);easing.type:Easing.OutCubic
    }
    readonly property bool motionDisabled:!Theme.panelMotionEnabled
    onMotionDisabledChanged:if(motionDisabled){tabFade.stop();content.opacity=1;}
    readonly property int rowGap: Theme.extraCompact ? 6 : Theme.compact ? 8 : 10
    readonly property int surfaceInset: Theme.extraCompact || width<280 ? 6 : Theme.compact ? 8 : 10
    readonly property int networkRowHeight: Math.max(34, Math.ceil(networkMetrics.height) + 12)
    FontMetrics {id: networkMetrics;font.pixelSize: Theme.fontSize(11)}
    spacing: rowGap
    implicitHeight: (detailHeader.visible ? detailHeader.implicitHeight+spacing : 0)+content.implicitHeight+(settingsLink.visible ? settingsLink.implicitHeight+spacing : 0)
    onSectionChanged: {
        animateTab();
        liftedControl="";refocusControl="";arranging=false;
        selectedSsid="";selectedNetworkItem=null;audioPicker="";if(sessionActions)sessionActions.confirmSleep=false;
        if(wifiPassword)wifiPassword.text="";
        if(body && body.contentItem)body.contentItem.contentY=0;
        if(section===1 && System.values.wifiEnabled)System.refreshWifi();
    }
    RowLayout {
        id: detailHeader
        visible: quick.section!==0
        Layout.fillWidth:true;spacing:quick.rowGap
        IconButton {
            id:detailBack;objectName:"quickDetailBack";iconName:"go-previous";hint:"Back to Quick Settings"
            onClicked:quick.showOverview()
        }
        Text {
            Layout.fillWidth:true;Layout.minimumWidth:0;elide:Text.ElideRight
            text:quick.section===1 ? "Connections" : quick.section===2 ? "Power and session" : "Audio devices"
            color:Theme.text;font.pixelSize:Theme.headingSize;font.weight:Font.DemiBold
        }
    }
    ScrollView {
        id: body;objectName: "quickScrollBody"
        Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 0
        clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            id: content;width: body.availableWidth;spacing: quick.rowGap
        Repeater {
            id:quickRows
            model: quick.controlOrder
            delegate: RowLayout {
                id:controlRow
                required property string modelData
                required property int index
                property alias grip: handle
                spacing:2
                visible:quick.section===0;Layout.fillWidth:true
                opacity:quick.liftedControl===modelData ? .48 : 1
                Loader {
                    Layout.fillWidth:true;Layout.minimumWidth:0
                    sourceComponent: ({volume:volumeControl,brightness:brightnessControl,connections:connectionsControl,power:powerControl})[controlRow.modelData]
                }
                OrbitButton {
                    id:handle
                    objectName:"quickGrip_"+controlRow.modelData
                    visible: quick.arranging
                    bare:true;padding:0
                    Layout.preferredWidth:26;Layout.minimumWidth:26
                    Layout.preferredHeight:30;Layout.alignment:Qt.AlignTop
                    hint:"Reorder "+quick.controlNames[controlRow.modelData]+" · ↑/↓"
                    Accessible.name:hint
                    contentItem: DragGrip {ink:handle.activeFocus || handle.hovered ? Theme.accentInk : Theme.muted}
                    Keys.onPressed: event => {
                        if(event.key!==Qt.Key_Up && event.key!==Qt.Key_Down)return;
                        event.accepted=true;
                        const step=event.key===Qt.Key_Up ? -1 : 1;
                        if(!event.isAutoRepeat && controlRow.index+step>=0 && controlRow.index+step<quick.controlOrder.length){
                            quick.refocusControl=controlRow.modelData;
                            Orbit.moveQuickControl(controlRow.modelData,step);
                        }
                    }
                    TapHandler {
                        acceptedButtons:Qt.RightButton
                        onTapped:defaultsMenu.popup()
                    }
                    Menu {
                        id:defaultsMenu
                        MenuItem {
                            text:"Restore default order"
                            enabled:quick.controlOrder.join(",")!==quick.defaultOrder.join(",")
                            onTriggered:{quick.refocusControl=controlRow.modelData;Orbit.setPreference("quickControlOrder",quick.defaultOrder);}
                        }
                    }
                    DragHandler {
                        target:null
                        acceptedButtons:Qt.LeftButton
                        acceptedDevices:PointerDevice.Mouse | PointerDevice.TouchPad | PointerDevice.Stylus | PointerDevice.TouchScreen
                        cursorShape:active ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                        onGrabChanged:(transition,point)=>{
                            if(transition===PointerDevice.GrabExclusive){
                                quick.dragPoint=point.scenePosition;
                                quick.liftedControl=controlRow.modelData;
                                Orbit.hideTooltip();
                            } else if(transition===PointerDevice.UngrabExclusive)
                                quick.completeReorder(point.scenePosition);
                            else if(transition===PointerDevice.CancelGrabExclusive)
                                quick.liftedControl="";
                        }
                        onTranslationChanged:if(active)quick.dragPoint=centroid.scenePosition
                    }
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
                ColumnLayout {
                    objectName: "wifiJoinForm"
                    enabled: !quick.wifiBusy
                    visible: quick.selectedSsid!=="";Layout.fillWidth: true;Layout.margins: 4;spacing: quick.rowGap
                    RowLayout {
                        Layout.fillWidth: true
                        Text {text: "Join "+quick.selectedSsid;Layout.fillWidth:true;Layout.minimumWidth:0;elide:Text.ElideRight;color:Theme.text;font.pixelSize:Theme.fontSize(11);font.weight:Font.DemiBold;textFormat:Text.PlainText}
                        IconButton {
                            iconName:"close";hint:"Cancel joining this network"
                            onClicked:quick.cancelNetwork()
                        }
                    }
                    RowLayout {
                        readonly property int fieldHeight:Math.max(30,Theme.fontSize(12)+16)
                        Layout.fillWidth: true
                        OrbitField { id: wifiPassword;visible: quick.selectedSecure;objectName: "wifiPassword";placeholderText: "Wi-Fi password";echoMode: TextInput.Password;Layout.fillWidth: true;Layout.minimumWidth:0;implicitHeight:parent.fieldHeight;onAccepted:quick.connectSelectedNetwork() }
                        OrbitButton { text: "Join";implicitHeight:parent.fieldHeight;accent:true;onClicked: quick.connectSelectedNetwork() }
                    }
                }
                ColumnLayout {
                    objectName: "quickNetworks";visible: networks.count>0
                    Layout.fillWidth: true;Layout.minimumWidth: 0
                    spacing: 2
                    Repeater {
                        id: networks
                        // The backend caps scan results at 20. Use the panel's
                        // existing scroll view so the wheel never gets trapped.
                        model: quick.section===1 && System.values.wifiEnabled ? (System.values.wifiNetworks || []) : []
                        delegate: Rectangle {
                            id: networkRow
                            objectName: "wifiNetwork_"+modelData.ssid
                            required property var modelData
                            enabled: !quick.wifiBusy
                            activeFocusOnTab: true
                            function selectNetwork(){quick.chooseNetwork(modelData,networkRow);}
                            Accessible.role: Accessible.Button
                            Accessible.name: modelData.ssid
                            Accessible.description: (modelData.active ? "Connected · " : "")+(modelData.secure ? "Secured" : "Open network")+" · "+modelData.signal+"%"
                            Accessible.onPressAction: selectNetwork()
                            Keys.onReturnPressed: selectNetwork()
                            Keys.onEnterPressed: selectNetwork()
                            Keys.onSpacePressed: selectNetwork()
                            border.color: activeFocus ? Theme.focusColor : "transparent"
                            onActiveFocusChanged: if(activeFocus)quick.reveal(networkRow)
                            Layout.fillWidth: true;implicitHeight: quick.networkRowHeight;radius: Theme.corner(6)
                            color: wifiHit.containsMouse || quick.selectedSsid===modelData.ssid ? Theme.hover : "transparent"
                            RowLayout {
                                anchors.fill: parent;anchors.leftMargin: quick.surfaceInset;anchors.rightMargin: quick.surfaceInset;spacing: quick.rowGap
                                Text { text: modelData.ssid;Layout.fillWidth: true;Layout.minimumWidth: 0;elide: Text.ElideRight;color: Theme.text;font.pixelSize: Theme.fontSize(11);textFormat: Text.PlainText }
                                Text {
                                    text: modelData.active ? "Connected" : (modelData.secure && parent.width>=230 ? "Secured · " : "")+modelData.signal+"%"
                                    Layout.maximumWidth: Math.floor(parent.width*0.48)
                                    elide: Text.ElideRight;color: Theme.muted;font.pixelSize: Theme.fontSize(10)
                                }
                            }
                            MouseArea { id: wifiHit;anchors.fill: parent;hoverEnabled: true;onClicked: parent.selectNetwork() }
                        }
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
                visible: !!(Power.state.batteryPresent || Power.state.percentageAvailable || System.values.batteryPresent)
                SettingRow {
                    label: Power.state.percentageAvailable ? Power.state.batteryPercent+"%"+(Power.state.charging ? " · Charging" : "") : System.values.batteryPresent ? System.values.batteryPercent+"%" : Power.state.batteryPresent ? "Battery level unavailable" : "No system battery"
                    IconButton {iconName: "battery";hint: "Battery health";onClicked: Orbit.showPanel("battery")}
                }
            }
        }
        ColumnLayout {
            visible:quick.section===3;Layout.fillWidth:true;spacing:quick.rowGap
            Loader {
                active:quick.section===3;Layout.fillWidth:true
                sourceComponent:SettingsGroup {
                    Text {text:"Output";color:Theme.text;font.pixelSize:Theme.labelSize}
                    AudioDevicePicker {
                        objectName:"quickOutputPicker";accessibleLabel:"Output device"
                        devices:System.values.audioOutputs || [];selectedName:System.values.defaultOutput || ""
                        emptyLabel:"No output device";expanded:quick.audioPicker==="output"
                        onToggled:quick.audioPicker=expanded ? "" : "output"
                        onSelected:name=>{System.setOutputDevice(name);quick.audioPicker="";}
                    }
                    Text {text:"Microphone";color:Theme.text;font.pixelSize:Theme.labelSize}
                    AudioDevicePicker {
                        objectName:"quickInputPicker";accessibleLabel:"Microphone"
                        devices:System.values.audioInputs || [];selectedName:System.values.defaultInput || ""
                        emptyLabel:"No microphone";expanded:quick.audioPicker==="input"
                        onToggled:quick.audioPicker=expanded ? "" : "input"
                        onSelected:name=>{System.setInputDevice(name);quick.audioPicker="";}
                    }
                }
            }
            OrbitButton {
                text:"Sound settings";quiet:true;Layout.fillWidth:true
                onClicked:Orbit.openSettingsSection(8)
            }
        }
        }
    }
    ColumnLayout {
        id: settingsLink;visible:quick.section===0;Layout.fillWidth:true;spacing:Math.max(4,quick.rowGap-2)
        Rectangle {Layout.fillWidth:true;implicitHeight:1;color:Theme.separator}
        RowLayout {
            Layout.fillWidth:true;spacing:quick.rowGap
            readonly property bool showLabels: width>=240+Math.max(0,Theme.textScale-1)*80
            IconButton {
                id:arrangeButton;objectName:"quickArrange"
                iconName:quick.arranging ? "check" : "view-grid"
                hint:quick.arranging ? "Done arranging" : "Reorder Quick Settings"
                visible:typeof Orbit.dropQuickControl==="function"
                onClicked:quick.setArranging(!quick.arranging)
            }
            IconButton {
                objectName:"systemSettingsLink";iconName:"settings";hint:"Open Settings"
                text:parent.showLabels ? "Settings" : ""
                Layout.fillWidth:true;implicitHeight:Math.max(30,Theme.fontSize(11)+14)
                onClicked:Orbit.showPanel("system-settings")
            }
            IconButton {
                objectName:"quickUpdates";iconName:"updates";implicitHeight:Math.max(30,Theme.fontSize(11)+14)
                text:parent.showLabels ? "Updates" : ""
                Layout.fillWidth:true
                accessibleLabel:"Software updates"
                readonly property bool available:typeof DesktopTools!=="undefined" && DesktopTools!==null && !!DesktopTools.tools.updates && DesktopTools.tools.updates.available
                enabled:available;hint:available ? "Software updates" : "Install a software update manager to check for updates"
                onClicked:DesktopTools.open("updates")
            }
        }
    }

    Rectangle {
        objectName:"quickDropMarker"
        visible:!!quick.insertion
        parent:body
        x:0;width:content.width;height:2;radius:1
        y:visible ? Math.max(0,quick.insertion.y-(quick.insertion.after ? 0 : quick.rowGap/2))-body.contentItem.contentY : 0
        color:Theme.accentInk;z:10
    }
    component QuickStatus: OrbitButton {
        id: tile
        required property string glyph
        required property string heading
        required property string status
        Layout.fillWidth:true;Layout.minimumWidth:0
        implicitHeight:Math.max(46,statusRow.implicitHeight+12);quiet:true
        Accessible.name: heading
        Accessible.description: status
        contentItem:RowLayout {
            id:statusRow;spacing:8
            Image {
                Layout.minimumWidth:18;Layout.maximumWidth:18;Layout.preferredHeight:18;sourceSize:Qt.size(24,24)
                source:Theme.symbolicIconSource(tile.glyph,Theme.accentInk)
            }
            ColumnLayout {
                Layout.fillWidth:true;Layout.minimumWidth:0;spacing:1
                Text {Layout.fillWidth:true;Layout.minimumWidth:0;horizontalAlignment:Text.AlignLeft;elide:Text.ElideRight;text:tile.heading;font.pixelSize:Theme.fontSize(12);font.weight:Font.DemiBold;color:Theme.text}
                Text {Layout.fillWidth:true;Layout.minimumWidth:0;visible:!!tile.status;text:tile.status;elide:Text.ElideRight;textFormat:Text.PlainText;color:Theme.muted;font.pixelSize:Theme.detailSize}
            }
            Image {
                Layout.minimumWidth:16;Layout.maximumWidth:16;Layout.preferredHeight:16;sourceSize:Qt.size(24,24)
                source:Theme.symbolicIconSource("chevron-right")
            }
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
        property bool applyOnRelease: false
        property bool pending: false
        signal glyphActivated()
        signal detailsActivated(Item source)
        signal applied(int value)
        Layout.fillWidth: true;Layout.minimumWidth: 0;spacing: 0
        RowLayout {
            Layout.fillWidth: true;spacing: 5
            Text {
                text: level.title;color: Theme.text;font.pixelSize:Theme.fontSize(12);font.weight:Font.DemiBold
                Layout.fillWidth:true;Layout.minimumWidth:0;elide:Text.ElideRight
            }
            IconButton {
                id: levelDetail
                objectName:level.linkObjectName;iconName:"chevron-right"
                hint:level.currentDevice && level.currentDevice!==level.detailsHint ? level.detailsHint+": "+level.currentDevice : level.detailsHint
                accessibleLabel:level.detailsHint;onClicked:level.detailsActivated(levelDetail)
            }
        }
        RowLayout {
            visible:level.available;Layout.fillWidth:true;spacing:6
            TextMetrics {id: maximumPercentage;font.pixelSize:Theme.fontSize(11);text:"100%"}
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
                onMoved:{userAdjusting=true;if(!level.applyOnRelease || !pressed)levelTimer.restart();}
                onPressedChanged:{
                    if(pressed && level.applyOnRelease)levelTimer.stop();
                    else if(!pressed && userAdjusting){levelTimer.stop();level.applied(Math.round(value));userAdjusting=false;}
                }
                Timer {id:levelTimer;interval:120;onTriggered:{level.applied(Math.round(levelSlider.value));if(!levelSlider.pressed)levelSlider.userAdjusting=false;}}
            }
            Text {
                text:Math.round(levelSlider.value)+"%";color:Theme.muted
                font.pixelSize:Theme.fontSize(11);horizontalAlignment:Text.AlignRight
                Layout.preferredWidth:Math.ceil(maximumPercentage.advanceWidth)
            }
        }
        Text {
            visible:level.pending
            Layout.fillWidth:true;text:"Applying brightness…";color:Theme.muted;font.pixelSize:Theme.fontSize(10)
        }
        Text {
            visible:!level.available;Layout.fillWidth:true;text:level.unavailable;textFormat:Text.PlainText
            color:Theme.muted;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap
        }
    }
    Component {
        id:volumeControl
        QuickLevel {
            objectName:"quickSoundControls";title:"Volume";valueName:"Output volume"
            value:System.values.volume || 0;available:!!System.values.audioAvailable
            glyph:System.values.muted ? "mute" : "volume"
            glyphActionLabel:System.values.muted ? "Unmute" : "Mute"
            glyphObjectName:"soundMuteButton";onGlyphActivated:System.toggleMute()
            detailsHint:"Audio devices and microphone";linkObjectName:"audioDevicesLink"
            currentDevice:System.values.audioName || ""
            onDetailsActivated: source => quick.openDetails(3,source)
            onApplied: value => System.setVolume(value)
        }
    }
    Component {
        id:brightnessControl
        QuickLevel {
            title:"Brightness";valueName:"Display brightness";sliderObjectName:"brightnessSlider"
            value:(Brightness.state.pendingPercent!==undefined ? Brightness.state.pendingPercent : Brightness.state.percent) || 0
            minimum:1;available:!!Brightness.state.available;applyOnRelease:Brightness.state.backend==="ddc"
            pending:Brightness.state.pendingPercent!==undefined
            glyph:"display";currentDevice:Brightness.state.name || ""
            unavailable:"Unavailable on this display"
            detailsHint:"Brightness settings";onDetailsActivated:Orbit.openSettingsSection(15)
            onApplied: value => Brightness.setBrightness(value)
        }
    }
    Component {
        id:connectionsControl
        QuickStatus {
            id:connectionRow;objectName:"quickConnectionStatus";glyph:"network-wireless";heading:"Connections"
            status:System.values.networkAvailable ? (System.values.networkState || "Wi-Fi") : "Network unavailable"
            onClicked:quick.openDetails(1,connectionRow)
        }
    }
    Component {
        id:powerControl
        QuickStatus {
            id:powerRow;objectName:"quickPowerStatus";glyph:"system-shutdown";heading:"Power";status:quick.batteryStatus
            onClicked:quick.openDetails(2,powerRow)
        }
    }

}
