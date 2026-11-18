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
    property bool arranging: false
    property var stagedPositions: ({})
    readonly property bool canArrange: DisplayControls.state.arrangement===true && DisplayControls.outputs.length>1
    readonly property bool arrangementOverlap: topology.some((a,index)=>topology.slice(0,index).some(
        b=>a.x<b.x+b.w && b.x<a.x+a.w && a.y<b.y+b.h && b.y<a.y+a.h))
    readonly property bool arrangementDirty: topology.some(row=>{
        const base=DisplayControls.outputs.find(output=>output.name===row.name);
        return base && (base.x!==row.x || base.y!==row.y);
    })
    function startArrangement() {
        if(!canArrange || draft)return;
        stagedPositions=({});arranging=true;loadOutput(outputName);
    }
    function stagePosition(name,x,y,snap) {
        if(!arranging || !editing)return;
        const row=topology.find(output=>output.name===name);
        if(!row)return;
        x=Math.max(-32768,Math.min(32768,Math.round(x)));
        y=Math.max(-32768,Math.min(32768,Math.round(y)));
        if(snap){
            let bestX=24,bestY=24,finalX=x,finalY=y;
            for(const other of topology) {
                if(other.name===name)continue;
                for(const edge of [other.x,other.x+other.w,other.x-row.w,other.x+other.w-row.w]){
                    if(Math.abs(edge-x)<bestX){bestX=Math.abs(edge-x);finalX=edge;}
                }
                for(const edge of [other.y,other.y+other.h,other.y-row.h,other.y+other.h-row.h]){
                    if(Math.abs(edge-y)<bestY){bestY=Math.abs(edge-y);finalY=edge;}
                }
            }
            x=Math.max(-32768,Math.min(32768,finalX));y=Math.max(-32768,Math.min(32768,finalY));
        }
        stagedPositions=Object.assign({},stagedPositions,{[name]:{x:x,y:y}});
        if(name===outputName){xPosition.text=String(x);yPosition.text=String(y);}
    }
    function finishArrangement(apply) {
        const positions=topology.map(row=>({name:row.name,x:row.x,y:row.y}));
        arranging=false;stagedPositions=({});loadOutput(outputName);
        if(apply)DisplayControls.applyArrangement(positions);
    }
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
        const modeDraft=selected && !arranging && (panel.chosenMode!==row.mode || scale!==row.scale || transform!==row.transform);
        const staged=arranging ? stagedPositions[row.name] : null;
        return {name: row.name, x: staged ? staged.x : !arranging && selected && xPosition.acceptableInput ? Number(xPosition.text) : row.x,
            y: staged ? staged.y : !arranging && selected && yPosition.acceptableInput ? Number(yPosition.text) : row.y,
            w: !modeDraft && row.width>0 ? row.width : mode ? Math.ceil((sideways ? mode.height : mode.width) / scale) : 1,
            h: !modeDraft && row.height>0 ? row.height : mode ? Math.ceil((sideways ? mode.width : mode.height) / scale) : 1};
    })
    function loadOutput(name) {
        var row=DisplayControls.outputs.find(o => o.name===name) || DisplayControls.outputs[0];
        draft=false;
        if(!row){outputName="";return;}
        outputName=row.name;chosenMode=row.mode;chosenScale=row.scale;chosenTransform=row.transform;
        const pos=arranging && stagedPositions[row.name] ? stagedPositions[row.name] : row;
        xPosition.text=String(pos.x);yPosition.text=String(pos.y);expanded="";
    }
    Component.onCompleted: {
        loadOutput("");
        DisplayControls.refresh();
    }
    Connections {
        target: DisplayControls
        function onChanged() {
            if(panel.arranging && (!panel.canArrange || Object.keys(panel.stagedPositions).some(
                    name=>!DisplayControls.outputs.some(output=>output.name===name))))panel.finishArrangement(false);
            if(!DisplayControls.state.busy && !DisplayControls.state.pending
                    && (!panel.draft || !DisplayControls.outputs.some(output=>output.name===panel.outputName)))panel.loadOutput(panel.outputName);
        }
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
                    objectName: "displayModePicker";accessibleLabel: "Resolution and refresh rate";enabled: panel.editing && !panel.arranging
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
                enabled: panel.editing && !panel.arranging
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
                OrbitButton {
                    objectName:"displayEditArrangement";visible:panel.canArrange && !panel.arranging
                    Layout.fillWidth:true;text:"Arrange displays";enabled:!panel.draft
                    onClicked:panel.startArrangement()
                }
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
                        model: map.visible ? DisplayControls.outputs.map(row=>row.name) : []
                        OrbitButton {
                            id: displayTile
                            required property string modelData
                            readonly property var geometry: panel.topology.find(row=>row.name===modelData) || ({name:modelData,x:0,y:0,w:1,h:1})
                            objectName:"displayLayoutTile_"+modelData
                            property real dragRatio: 1
                            property point dragOrigin
                            property point dragDelta
                            z: tileDrag.active ? 2 : geometry.name === panel.outputName ? 1 : 0
                            x: (map.width-map.totalWidth*map.ratio)/2 + (geometry.x-map.leftEdge)*map.ratio + (tileDrag.active ? displayTile.dragDelta.x : 0)
                            y: (map.height-map.totalHeight*map.ratio)/2 + (geometry.y-map.topEdge)*map.ratio + (tileDrag.active ? displayTile.dragDelta.y : 0)
                            width: Math.max(2, geometry.w*map.ratio-2)
                            height: Math.max(2, geometry.h*map.ratio-2)
                            padding: 2
                            text: width >= 36 && height >= 21 ? geometry.name : ""
                            clip: true
                            hint: geometry.name
                            Accessible.name: "Select display "+geometry.name
                            accent: geometry.name === panel.outputName
                            onClicked: panel.loadOutput(geometry.name)
                            Accessible.description: panel.arranging ? "Use arrow keys to move this display" : ""
                            Keys.onPressed: event=>{
                                if(!panel.arranging)return;
                                const step=event.modifiers&Qt.ShiftModifier ? 1 : 32;
                                const dx=event.key===Qt.Key_Right ? step : event.key===Qt.Key_Left ? -step : 0;
                                const dy=event.key===Qt.Key_Down ? step : event.key===Qt.Key_Up ? -step : 0;
                                if(!dx && !dy)return;
                                panel.loadOutput(geometry.name);
                                panel.stagePosition(geometry.name,geometry.x+dx,geometry.y+dy,false);event.accepted=true;
                            }
                            DragHandler {
                                id:tileDrag;enabled:panel.arranging;target:null
                                onTranslationChanged:if(active){
                                    displayTile.dragDelta=Qt.point(translation.x-displayTile.dragOrigin.x,
                                                                   translation.y-displayTile.dragOrigin.y);
                                }
                                onActiveChanged:{
                                    if(active){
                                        displayTile.dragRatio=map.ratio;
                                        displayTile.dragOrigin=Qt.point(translation.x,translation.y);
                                        displayTile.dragDelta=Qt.point(0,0);
                                        panel.loadOutput(displayTile.geometry.name);
                                    }else if(panel.arranging){
                                        const row=displayTile.geometry;
                                        panel.stagePosition(row.name,row.x+displayTile.dragDelta.x/displayTile.dragRatio,
                                                            row.y+displayTile.dragDelta.y/displayTile.dragRatio,true);
                                    }
                                }
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true;Layout.margins: 6
                    Text {text: "X";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
                    OrbitField {id: xPosition;objectName: "displayX";Accessible.name: "Display horizontal position";Layout.fillWidth: true;implicitHeight: 30;text: "0";maximumLength: 6;readOnly:panel.canArrange && !panel.arranging;onTextEdited: {
                        if(panel.arranging && xPosition.acceptableInput && yPosition.acceptableInput)
                            panel.stagePosition(panel.outputName,Number(xPosition.text),Number(yPosition.text),false);
                        else if(!panel.arranging)panel.draft=true;
                    } validator: IntValidator {bottom: -32768;top: 32768}}
                    Text {text: "Y";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
                    OrbitField {id: yPosition;objectName: "displayY";Accessible.name: "Display vertical position";Layout.fillWidth: true;implicitHeight: 30;text: "0";maximumLength: 6;readOnly:panel.canArrange && !panel.arranging;onTextEdited: {
                        if(panel.arranging && xPosition.acceptableInput && yPosition.acceptableInput)
                            panel.stagePosition(panel.outputName,Number(xPosition.text),Number(yPosition.text),false);
                        else if(!panel.arranging)panel.draft=true;
                    } validator: IntValidator {bottom: -32768;top: 32768}}
                }
                Text {Layout.fillWidth: true;Layout.margins: 6;text: panel.arranging ? "Drag a display or move it with the arrow keys. Shift + arrow moves one pixel." : "Positions use logical pixels. Apply resolution or rotation changes before arranging displays.";color: Theme.faint;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap}
            }
        }
    }
    Text {
        objectName: "displayError";visible: text.length>0;text: panel.arranging && panel.arrangementOverlap ? "Displays overlap. Move their edges apart." : DisplayControls.state.error || ""
        color: Theme.muted;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap
        Layout.fillWidth: true;textFormat: Text.PlainText
    }
    RowLayout {
        Layout.fillWidth: true
        IconButton {objectName: "displayRefresh";iconName: "refresh";hint: "Refresh displays";enabled: !DisplayControls.state.busy && !panel.pending;onClicked: DisplayControls.refresh()}
        Item {Layout.fillWidth: true}
        OrbitButton {
            visible:panel.arranging;text:"Cancel";onClicked:panel.finishArrangement(false)
        }
        OrbitButton {
            objectName:"displayApplyArrangement";visible:panel.arranging;text:"Apply arrangement";accent:true
            enabled:panel.editing && panel.arrangementDirty && !panel.arrangementOverlap && xPosition.acceptableInput && yPosition.acceptableInput
            onClicked:panel.finishArrangement(true)
        }
        OrbitButton {
            id: applyButton;visible:!panel.arranging;objectName: "displayApply";text: "Apply";accent: true
            enabled: !DisplayControls.state.busy && !panel.pending && panel.editing && xPosition.acceptableInput && yPosition.acceptableInput
            onClicked: {
                panel.draft=false;
                DisplayControls.apply(panel.outputName,panel.chosenMode,panel.chosenScale,panel.chosenTransform,Number(xPosition.text),Number(yPosition.text));
            }
        }
    }
}
