import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: view;spacing:8
    property string pendingDelete: ""
    function saveDraft(){Arrangements.save(name.text);}
    Connections {target:Arrangements;function onSaved(savedName){if(name.text===savedName)name.text="";}}
    Text {Layout.fillWidth:true;text:"Save application positions and workspaces. Existing windows are reused; app contents and browser tabs are not saved.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
    RowLayout {
        Layout.fillWidth:true
        OrbitField {id:name;objectName:"layoutName";Layout.fillWidth:true;placeholderText:"Layout name";maximumLength:48;onAccepted:if(text.trim() && !Arrangements.busy){view.saveDraft();}}
        OrbitButton {objectName:"saveCurrentLayout";text:"Save current";enabled:Arrangements.available && !Arrangements.busy && name.text.trim().length>0;onClicked:{view.saveDraft();}}
    }
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
                    OrbitButton {text:view.pendingDelete===modelData.id?"Confirm remove":"Remove";quiet:true;enabled:!Arrangements.busy;onClicked:{if(view.pendingDelete===modelData.id){Arrangements.remove(modelData.id);view.pendingDelete="";}else view.pendingDelete=modelData.id;}}
                }
            }
            Text {visible:Arrangements.layouts.length===0;text:"No saved layouts yet";color:Theme.muted;font.pixelSize:Theme.fontSize(12)}
            SettingsGroup {
                visible:!!Arrangements.preview.id;title:Arrangements.preview.name || "Preview"
                Repeater {
                    model:Arrangements.preview.rows || []
                    delegate:ColumnLayout {
                        required property var modelData
                        Layout.fillWidth:true
                        Text {Layout.fillWidth:true;text:modelData.name+" · Workspace "+modelData.workspace+" · "+modelData.status;wrapMode:Text.Wrap;color:Theme.text;font.pixelSize:Theme.fontSize(12)}
                        ComboBox {
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
                    OrbitButton {text:"Refresh windows";quiet:true;enabled:!Arrangements.busy;onClicked:Arrangements.refreshPreview()}
                    OrbitButton {objectName:"applyLayout";text:"Apply layout";accent:true;enabled:!Arrangements.busy && (Arrangements.preview.rows || []).length>0 && (Arrangements.preview.rows || []).every((r,i,rows)=>r.selected!=="" && rows.findIndex(other=>other.selected===r.selected)===i);onClicked:Arrangements.apply()}
                }
                Text {Layout.fillWidth:true;text:"For missing apps, choose Open, then Refresh windows. If an app has several windows, choose each one explicitly. Apply can be undone.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            }
        }
    }
}
