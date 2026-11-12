import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: panel;objectName: "displayPanel"
    property string outputName: ""
    property string chosenMode: ""
    property real chosenScale: 1
    property string chosenTransform: "normal"
    property string expanded: ""
    property bool draft: false
    readonly property var currentOutput: DisplayControls.outputs.find(o => o.name===outputName) || ({modes:[]})
    readonly property bool pending: DisplayControls.state.pending
    readonly property bool editing: DisplayControls.state.available && !DisplayControls.state.busy && !pending
    spacing: 10
    function focusConfirmation() {
        if (pending && applyButton.visible && applyButton.enabled)
            applyButton.forceActiveFocus(Qt.TabFocusReason);
    }
    onPendingChanged: if (pending) Qt.callLater(focusConfirmation)
    function loadOutput(name) {
        var row=DisplayControls.outputs.find(o => o.name===name) || DisplayControls.outputs[0];
        draft=false;
        if(!row){outputName="";return;}
        outputName=row.name;chosenMode=row.mode;chosenScale=row.scale;chosenTransform=row.transform;xPosition.text=String(row.x);yPosition.text=String(row.y);expanded="";
    }
    Component.onCompleted: {
        loadOutput("");
        DisplayControls.refresh();
        if (pending) Qt.callLater(focusConfirmation);
    }
    Connections {
        target: DisplayControls
        function onChanged(){if(!DisplayControls.state.busy && !DisplayControls.state.pending && (!panel.draft || !DisplayControls.outputs.some(o => o.name===panel.outputName)))panel.loadOutput(panel.outputName);}
    }
    ScrollView {
        id: body
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 0
        clip: true
        contentWidth: availableWidth
        implicitHeight: content.implicitHeight
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            id: content;width: body.availableWidth;spacing: 10
            SettingsGroup {
                title: "Display"
                AudioDevicePicker {
                    objectName: "displayOutputPicker";accessibleLabel: "Display";enabled: panel.editing
                    devices: DisplayControls.outputs.map(o => ({name:o.name,description:o.name+" · "+o.label}))
                    selectedName: panel.outputName;emptyLabel: "No configurable display"
                    expanded: panel.expanded==="output"
                    onToggled: panel.expanded=expanded ? "" : "output"
                    onSelected: name => panel.loadOutput(name)
                }
                AudioDevicePicker {
                    objectName: "displayModePicker";accessibleLabel: "Resolution and refresh rate";enabled: panel.editing
                    visibleChoices: 7
                    devices: panel.currentOutput.modes.map(m => ({name:m.value,description:m.label}))
                    selectedName: panel.chosenMode;emptyLabel: "No modes reported"
                    expanded: panel.expanded==="mode"
                    onToggled: panel.expanded=expanded ? "" : "mode"
                    onSelected: name => {panel.draft=true;panel.chosenMode=name;panel.expanded="";}
                }
                Text {Layout.fillWidth: true;Layout.margins: 6;text: "Changes apply for 15 seconds. Keep them to save, or they automatically revert.";wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
            }
            SettingsGroup {
                title: "Scale and rotation"
                enabled: panel.editing
                AudioDevicePicker {
                    objectName: "displayScalePicker";accessibleLabel: "Display scale"
                    visibleChoices: 5
                    devices: [.5,.75,1,1.25,1.5,1.75,2,2.5,3].map(s => ({name:String(s),description:Math.round(s*100)+"%"}))
                    selectedName: String(panel.chosenScale);expanded: panel.expanded==="scale"
                    onToggled: panel.expanded=expanded ? "" : "scale"
                    onSelected: name => {panel.draft=true;panel.chosenScale=Number(name);panel.expanded="";}
                }
                Text {
                    Layout.fillWidth: true;Layout.margins: 6
                    text: "Display scale changes the size of apps and desktop controls. Select a scale, then choose Apply."
                    wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11)
                }
                SettingsSegments {
                    objectName: "displayRotation";Layout.fillWidth: true;segmentWidth: Math.max(42,Math.floor((body.availableWidth-24)/4))
                    value: panel.chosenTransform;options: [{label:"Normal",value:"normal"},{label:"90°",value:"90"},{label:"180°",value:"180"},{label:"270°",value:"270"}]
                    onSelected: value => {panel.draft=true;panel.chosenTransform=value;}
                }
            }
            SettingsGroup {
                title: "Arrangement"
                visible: DisplayControls.outputs.length>1
                enabled: panel.editing
                RowLayout {
                    Layout.fillWidth: true;Layout.margins: 6
                    Text {text: "X";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
                    OrbitField {id: xPosition;objectName: "displayX";Accessible.name: "Display horizontal position";Layout.fillWidth: true;implicitHeight: 30;text: "0";maximumLength: 6;onTextEdited: panel.draft=true;validator: IntValidator {bottom: -32768;top: 32768}}
                    Text {text: "Y";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
                    OrbitField {id: yPosition;objectName: "displayY";Accessible.name: "Display vertical position";Layout.fillWidth: true;implicitHeight: 30;text: "0";maximumLength: 6;onTextEdited: panel.draft=true;validator: IntValidator {bottom: -32768;top: 32768}}
                }
                Text {Layout.fillWidth: true;Layout.margins: 6;text: "Positions use logical pixels. Put a display to the right by setting X to the other display’s logical width.";color: Theme.faint;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap}
            }
        }
    }
    Text {
        objectName: "displayError";visible: text.length>0;text: DisplayControls.state.error || ""
        color: Theme.muted;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap
        Layout.fillWidth: true;textFormat: Text.PlainText
    }
    Text {
        objectName: "displayCountdown";visible: panel.pending
        text: "Keep these settings? Reverting in "+DisplayControls.state.secondsRemaining+" seconds."
        color: Theme.text;font.pixelSize: Theme.fontSize(12);wrapMode: Text.Wrap;Layout.fillWidth: true
    }
    RowLayout {
        Layout.fillWidth: true
        OrbitButton {objectName: "displayRefresh";text: "Refresh";quiet: true;enabled: !DisplayControls.state.busy && !panel.pending;onClicked: DisplayControls.refresh()}
        Item {Layout.fillWidth: true}
        OrbitButton {objectName: "displayRevert";visible: panel.pending;text: "Revert";enabled: !DisplayControls.state.busy;onClicked: DisplayControls.revert()}
        OrbitButton {
            id: applyButton;objectName: "displayApply";text: panel.pending ? "Keep settings" : "Apply";accent: true
            enabled: !DisplayControls.state.busy && (panel.pending || (panel.editing && xPosition.acceptableInput && yPosition.acceptableInput))
            onClicked: {
                if (panel.pending) DisplayControls.confirm();
                else {
                    panel.draft=false;
                    DisplayControls.apply(panel.outputName,panel.chosenMode,panel.chosenScale,panel.chosenTransform,Number(xPosition.text),Number(yPosition.text));
                }
            }
        }
    }
}
