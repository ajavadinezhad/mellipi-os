import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: view;spacing: 10
    readonly property var state: Recovery.state
    property string section: "backup"
    property bool confirmSettings: false
    RowLayout {
        Layout.fillWidth: true
        Repeater {
            model: [{id:"backup",name:"Back up"},{id:"restore",name:"Restore"},{id:"recovery",name:"Recovery"}]
            OrbitButton {required property var modelData;text:modelData.name;Layout.fillWidth:true;quiet:view.section!==modelData.id;onClicked:{view.section=modelData.id;view.confirmSettings=false;}}
        }
    }
    Text {visible:!!view.state.error;Layout.fillWidth:true;text:view.state.error || "";textFormat:Text.PlainText;wrapMode:Text.Wrap;color:Theme.accent;font.pixelSize:Theme.fontSize(11)}
    Text {visible:!!view.state.message;Layout.fillWidth:true;text:view.state.message || "";textFormat:Text.PlainText;wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
    RowLayout {
        visible:view.state.busy;Layout.fillWidth:true
        Text {text:(view.state.operation || "").indexOf("picker:")===0 ? "Choose files in the open dialog…" : "Working…";color:Theme.muted;font.pixelSize:Theme.fontSize(11);Layout.fillWidth:true}
        OrbitButton {text:"Cancel";quiet:true;onClicked:Recovery.cancel()}
    }
    ColumnLayout {
        visible:view.section==="backup";Layout.fillWidth:true;spacing:8
        Text {text:"Desktop settings";color:Theme.text;font.pixelSize:Theme.fontSize(14)}
        Text {Layout.fillWidth:true;text:"Includes appearance, pinned apps, saved window layouts and display preferences. Choose personal files separately. Backups are not encrypted; choose trusted storage.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        SettingsGroup {
            title:"Destination"
            RowLayout {
                Layout.fillWidth:true
                OrbitField {objectName:"backupDestination";Layout.fillWidth:true;text:view.state.backupParent || "";enabled:!view.state.busy;placeholderText:"Backup folder";onEditingFinished:Recovery.setPath("backupParent",text)}
                OrbitButton {text:"Browse…";enabled:!view.state.busy;onClicked:Recovery.chooseDirectory("backupParent")}
            }
        }
        SettingsGroup {
            title:"Personal files · optional"
            RowLayout {
                Layout.fillWidth:true
                OrbitButton {text:"Add files…";Layout.fillWidth:true;enabled:!view.state.busy;onClicked:Recovery.chooseFiles()}
                OrbitButton {text:"Add folder…";Layout.fillWidth:true;enabled:!view.state.busy;onClicked:Recovery.chooseDirectory("personal")}
                OrbitButton {text:"Clear";quiet:true;enabled:!view.state.busy && (view.state.personalFiles || []).length>0;onClicked:Recovery.clearFiles()}
            }
            Text {Layout.fillWidth:true;text:(view.state.personalFiles || []).length ? view.state.personalFiles.join("\n") : "Desktop settings only";textFormat:Text.PlainText;wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }
        OrbitButton {objectName:"createDesktopBackup";text:"Create backup";accent:true;Layout.fillWidth:true;enabled:!view.state.busy && !!view.state.backupParent;onClicked:Recovery.create()}
    }
    ColumnLayout {
        visible:view.section==="restore";Layout.fillWidth:true;spacing:8
        SettingsGroup {
            title:"Backup"
            RowLayout {
                Layout.fillWidth:true
                OrbitField {objectName:"restoreBackupPath";Layout.fillWidth:true;text:view.state.backupPath || "";enabled:!view.state.busy;placeholderText:"Mellipi backup folder";onEditingFinished:{Recovery.setPath("backupPath",text);view.confirmSettings=false;}}
                OrbitButton {text:"Browse…";enabled:!view.state.busy;onClicked:{view.confirmSettings=false;Recovery.chooseDirectory("backupPath");}}
            }
            OrbitButton {objectName:"verifyDesktopBackup";text:"Verify backup";Layout.fillWidth:true;enabled:!view.state.busy && !!view.state.backupPath;onClicked:Recovery.inspect()}
        }
        SettingsGroup {
            visible:!!view.state.preview.verified;title:"Restore files & folders"
            Text {Layout.fillWidth:true;text:"Files and empty folders go into a new Mellipi-restored folder. Timestamps and safe owner-executable permissions are preserved. Existing files are never replaced.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            RowLayout {
                Layout.fillWidth:true
                OrbitField {Layout.fillWidth:true;text:view.state.restoreParent || "";enabled:!view.state.busy;placeholderText:"Restore destination";onEditingFinished:Recovery.setPath("restoreParent",text)}
                OrbitButton {text:"Browse…";enabled:!view.state.busy;onClicked:Recovery.chooseDirectory("restoreParent")}
            }
            OrbitButton {objectName:"restoreBackupFiles";text:"Restore to new folder";enabled:!view.state.busy;Layout.fillWidth:true;onClicked:Recovery.restore()}
        }
        SettingsGroup {
            visible:!!view.state.preview.settings;title:"Desktop settings"
            Text {Layout.fillWidth:true;text:"Restore settings at your next login. Current settings are saved first; edits made after scheduling are kept. Your apps stay open.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            OrbitButton {visible:!view.confirmSettings && !view.state.restorePending;text:"Restore desktop settings…";enabled:!view.state.busy;Layout.fillWidth:true;onClicked:view.confirmSettings=true}
            OrbitButton {visible:view.confirmSettings && !view.state.restorePending;objectName:"confirmRestoreDesktopSettings";text:"Schedule settings restore";accent:true;enabled:!view.state.busy;Layout.fillWidth:true;onClicked:{Recovery.queueSettings();view.confirmSettings=false;}}
        }
        OrbitButton {visible:view.state.restorePending;text:"Cancel scheduled settings restore";enabled:!view.state.busy;Layout.fillWidth:true;onClicked:Recovery.cancelSettings()}
    }
    ColumnLayout {
        visible:view.section==="recovery";Layout.fillWidth:true;spacing:8
        Text {text:"Last working desktop";color:Theme.text;font.pixelSize:Theme.fontSize(14)}
        Text {Layout.fillWidth:true;text:"After checking this desktop works, save its package versions. If an update breaks login, press Ctrl+Alt+F3, sign in, and run the recovery command. APT verifies packages and asks before installing; a trusted repository connection is required.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        OrbitButton {objectName:"saveWorkingDesktop";text:"Save this working version";enabled:!view.state.busy;Layout.fillWidth:true;onClicked:Recovery.saveWorking()}
        SettingsGroup {
            visible:!!view.state.checkpoint.available;title:"Recovery command"
            TextEdit {objectName:"desktopRecoveryCommand";Layout.fillWidth:true;text:view.state.checkpoint.command || "";readOnly:true;selectByMouse:true;wrapMode:TextEdit.WrapAnywhere;color:Theme.text;font.pixelSize:Theme.fontSize(11);Accessible.name:"Desktop package recovery command"}
            Text {Layout.fillWidth:true;text:"Package recovery does not restore documents or undo kernel updates. It does not restart the current session. Save work before logging out to activate the restored compositor.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }
    }
    OrbitButton {visible:!!view.state.resultPath;text:"Open saved folder";quiet:true;Layout.fillWidth:true;onClicked:Recovery.openResult()}
}
