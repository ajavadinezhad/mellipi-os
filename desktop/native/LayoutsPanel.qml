import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: view;spacing:8
    property string pendingDelete: ""
    function saveDraft(){Arrangements.save(name.text, folder.text); }
    Connections {target:Arrangements;function onSaved(savedName){if(name.text.trim()===savedName){name.text="";folder.text="";}}}
    Text {Layout.fillWidth:true;text:"Save this setup";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.detailSize}
    RowLayout {
        Layout.fillWidth:true
        OrbitField {id:name;objectName:"layoutName";Layout.fillWidth:true;placeholderText:"Layout name";maximumLength:48;onAccepted:if(text.trim() && !Arrangements.busy){view.saveDraft();}}
        IconButton {objectName:"saveCurrentLayout";iconName:"save";hint:"Save layout";implicitWidth:Math.max(36,name.implicitHeight);implicitHeight:implicitWidth;enabled:Arrangements.available && !Arrangements.busy && name.text.trim().length>0;onClicked:{view.saveDraft();}}
    }
    OrbitField {id:folder;Layout.fillWidth:true;placeholderText:"Project folder (optional)";maximumLength:4096;Accessible.name:"Optional project folder path"}
    ScrollView {
        Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
        ScrollBar.horizontal.policy:ScrollBar.AlwaysOff
        ColumnLayout {
            width:parent.width;spacing:6
            Repeater {
                model:Arrangements.layouts
                delegate:RowLayout {
                    required property var modelData
                    Layout.fillWidth:true
                    OrbitButton {Layout.fillWidth:true;objectName:"savedLayout";text:modelData.name+" · "+modelData.count+" windows";enabled:!Arrangements.busy;onClicked:Arrangements.openPreview(modelData.id)}
                    IconButton {
                        iconName:"trash";hint:"Remove layout: "+modelData.name
                        implicitWidth:Math.max(36,Theme.labelSize+16);implicitHeight:implicitWidth
                        visible:view.pendingDelete!==modelData.id;enabled:!Arrangements.busy
                        onClicked:view.pendingDelete=modelData.id
                    }
                    OrbitButton {
                        text:"Confirm remove";hint:"Permanently remove the saved layout "+modelData.name
                        visible:view.pendingDelete===modelData.id;enabled:!Arrangements.busy
                        onClicked:{Arrangements.remove(modelData.id);view.pendingDelete="";}
                    }
                    IconButton {
                        iconName:"close";hint:"Cancel removal";visible:view.pendingDelete===modelData.id
                        onClicked:view.pendingDelete=""
                    }
                }
            }
            Text {visible:Arrangements.layouts.length===0;text:"No saved layouts yet";color:Theme.muted;font.pixelSize:Theme.labelSize}
            SettingsGroup {
                visible:!!Arrangements.preview.id;title:Arrangements.preview.name || "Preview"
                Repeater {
                    model:Arrangements.preview.rows || []
                    delegate:ColumnLayout {
                        required property var modelData
                        Layout.fillWidth:true
                        Text {Layout.fillWidth:true;text:modelData.name+" · Workspace "+modelData.workspace+" · "+modelData.status;wrapMode:Text.Wrap;color:Theme.text;font.pixelSize:Theme.labelSize}
                        SettingsChoice {
                            Layout.fillWidth:true;visible:modelData.candidates.length>0;enabled:!Arrangements.busy
                            model:[{id:"",name:"Choose open window…"}].concat(modelData.candidates);textRole:"name"
                            currentIndex:Math.max(0,model.findIndex(c=>c.id===modelData.selected))
                            Accessible.name:"Window for "+modelData.name
                            onActivated:index=>Arrangements.choose(modelData.index,model[index].id)
                        }
                        OrbitButton {visible:!modelData.candidates.length && modelData.installed;text:"Open "+modelData.name;enabled:!Arrangements.busy;onClicked:Orbit.launchForLayout(modelData.app)}
                    }
                }
                RowLayout {
                    Layout.fillWidth:true
                    OrbitButton {
                        text:"Resume workspace"
                        visible:!!Arrangements.preview.folder || (Arrangements.preview.rows || []).some(r=>!r.selected && !r.candidates.length && r.installed)
                        enabled:!Arrangements.busy
                        onClicked:Arrangements.resume()
                    }
                    OrbitButton {objectName:"applyLayout";text:"Apply layout";accent:true;enabled:!Arrangements.busy && (Arrangements.preview.rows || []).length>0 && (Arrangements.preview.rows || []).every((r,i,rows)=>r.selected!=="" && rows.findIndex(other=>other.selected===r.selected)===i);onClicked:Arrangements.apply()}
                }
                Text {Layout.fillWidth:true;text:"Resume opens missing apps. If several windows match, choose which one to use.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.detailSize}
            }
        }
    }
}
