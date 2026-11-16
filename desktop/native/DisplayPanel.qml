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
    readonly property var activeMode: currentOutput.modes.find(m => m.value===currentOutput.mode)
    readonly property var selectableModes: currentOutput.modes.filter(m => m.standard !== false)
    readonly property var selectedMode: currentOutput.modes.find(m => m.value===chosenMode)
    readonly property bool pending: DisplayControls.state.pending
    readonly property bool editing: DisplayControls.state.available && !DisplayControls.state.busy && !pending
    spacing: 10
    readonly property var topology: DisplayControls.outputs.map(function(row) {
        const selected = row.name === panel.outputName;
        const mode = selected ? panel.selectedMode : row.modes.find(m => m.value === row.mode);
        const transform = selected ? panel.chosenTransform : row.transform;
        const scale = selected ? panel.chosenScale : row.scale;
        const sideways = ["90","270","flipped-90","flipped-270"].includes(transform);
        return {name: row.name, x: selected && xPosition.acceptableInput ? Number(xPosition.text) : row.x,
            y: selected && yPosition.acceptableInput ? Number(yPosition.text) : row.y,
            w: mode ? Math.ceil((sideways ? mode.height : mode.width) / scale) : Math.max(1,row.width),
            h: mode ? Math.ceil((sideways ? mode.width : mode.height) / scale) : Math.max(1,row.height)};
    })
    function loadOutput(name) {
        var row=DisplayControls.outputs.find(o => o.name===name) || DisplayControls.outputs[0];
        draft=false;
        if(!row){outputName="";return;}
        outputName=row.name;chosenMode=row.mode;chosenScale=row.scale;chosenTransform=row.transform;xPosition.text=String(row.x);yPosition.text=String(row.y);expanded="";
    }
    Component.onCompleted: {
        loadOutput("");
        DisplayControls.refresh();
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
                    devices: DisplayControls.outputs.map(o => ({name:o.name,description:o.label && o.label!==o.name ? o.label+" · "+o.name : o.name}))
                    selectedName: panel.outputName;emptyLabel: "No configurable display"
                    expanded: panel.expanded==="output"
                    onToggled: panel.expanded=expanded ? "" : "output"
                    onSelected: name => panel.loadOutput(name)
                }
                AudioDevicePicker {
                    objectName: "displayModePicker";accessibleLabel: "Resolution and refresh rate";enabled: panel.editing
                    visibleChoices: 7
                    devices: panel.selectableModes.map(m => ({name:m.value,description:m.label}))
                    selectedName: panel.chosenMode
                    readonly property string customLabel: panel.activeMode && panel.activeMode.standard===false
                        ? panel.activeMode.label+" · Current custom mode" : ""
                    chooseLabel: customLabel || "Choose a resolution"
                    emptyLabel: customLabel || "No standard modes reported"
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
                SettingsSegments {
                    objectName: "displayRotation";Layout.fillWidth: true;segmentWidth: Math.max(42,Math.floor((body.availableWidth-24)/4))
                    value: panel.chosenTransform;options: [{label:"Normal",value:"normal"},{label:"90°",value:"90"},{label:"180°",value:"180"},{label:"270°",value:"270"}]
                    onSelected: value => {panel.draft=true;panel.chosenTransform=value;}
                }
                Text {
                    objectName: "displayEffectiveSize"
                    Layout.fillWidth: true;Layout.margins: 6
                    visible: panel.selectedMode !== undefined
                    text: {
                        const mode = panel.selectedMode;
                        if (!mode || !mode.width || !mode.height || panel.chosenScale <= 0) return "";
                        const sideways = ["90", "270", "flipped-90", "flipped-270"].includes(panel.chosenTransform);
                        const width = Math.ceil((sideways ? mode.height : mode.width) / panel.chosenScale);
                        const height = Math.ceil((sideways ? mode.width : mode.height) / panel.chosenScale);
                        return "Effective display size: " + width + " × " + height + " logical pixels";
                    }
                    wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11)
                }
            }
            SettingsGroup {
                title: "Arrangement"
                visible: DisplayControls.outputs.length>1
                enabled: panel.editing
                Rectangle {
                    id: map
                    objectName: "displayTopology"
                    Layout.fillWidth: true
                    Layout.margins: 6
                    implicitHeight: Math.max(104, 92 * Theme.textScale)
                    color: Theme.surface
                    radius: Theme.corner(6)
                    clip: true
                    readonly property real leftEdge: Math.min(0,...panel.topology.map(o => o.x))
                    readonly property real topEdge: Math.min(0,...panel.topology.map(o => o.y))
                    readonly property real totalWidth: Math.max(1,...panel.topology.map(o => o.x+o.w))-leftEdge
                    readonly property real totalHeight: Math.max(1,...panel.topology.map(o => o.y+o.h))-topEdge
                    readonly property real ratio: Math.max(0.0001,Math.min((width-12)/totalWidth,(height-12)/totalHeight))
                    Repeater {
                        model: map.visible ? panel.topology : []
                        OrbitButton {
                            required property var modelData
                            z: modelData.name === panel.outputName ? 1 : 0
                            x: (map.width-map.totalWidth*map.ratio)/2 + (modelData.x-map.leftEdge)*map.ratio
                            y: (map.height-map.totalHeight*map.ratio)/2 + (modelData.y-map.topEdge)*map.ratio
                            width: Math.max(2, modelData.w*map.ratio-2)
                            height: Math.max(2, modelData.h*map.ratio-2)
                            padding: 2
                            text: width >= 36 && height >= 21 ? modelData.name : ""
                            clip: true
                            hint: modelData.name
                            Accessible.name: "Select display "+modelData.name
                            accent: modelData.name === panel.outputName
                            onClicked: panel.loadOutput(modelData.name)
                        }
                    }
                }
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
    RowLayout {
        Layout.fillWidth: true
        IconButton {objectName: "displayRefresh";iconName: "refresh";hint: "Refresh displays";enabled: !DisplayControls.state.busy && !panel.pending;onClicked: DisplayControls.refresh()}
        Item {Layout.fillWidth: true}
        OrbitButton {
            id: applyButton;objectName: "displayApply";text: "Apply";accent: true
            enabled: !DisplayControls.state.busy && !panel.pending && panel.editing && xPosition.acceptableInput && yPosition.acceptableInput
            onClicked: {
                panel.draft=false;
                DisplayControls.apply(panel.outputName,panel.chosenMode,panel.chosenScale,panel.chosenTransform,Number(xPosition.text),Number(yPosition.text));
            }
        }
    }
}
