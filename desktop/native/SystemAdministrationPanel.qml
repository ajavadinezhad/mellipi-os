import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: administration
    property string section: "users"
    property int userId: -1
    property bool adding: false
    property bool resetPassword: false
    property bool confirmRemove: false
    property string usersSignature: ""
    readonly property var state: typeof DesktopTools.systemState!=="undefined" ? DesktopTools.systemState : ({busy:false,error:"",usersAvailable:false,clockAvailable:false,zones:[]})
    readonly property var users: typeof DesktopTools.systemUsers!=="undefined" ? DesktopTools.systemUsers : []
    readonly property var selected: users.find(row=>row.id===userId) || ({id:-1,name:"",displayName:"",current:false,administrator:false,locked:false,loggedIn:false,sessionsKnown:false})
    readonly property var zoneRows: (state.zones || []).filter(zone=>zone.toLowerCase().includes(zoneSearch.text.toLowerCase())).map(zone=>({id:zone,name:zone.replace(/_/g," ")}))
    Layout.fillWidth: true;spacing: 8
    function clearPasswords(){newPassword.text="";newConfirm.text="";resetValue.text="";resetConfirm.text="";}
    function loadUser(){displayName.text=selected.displayName || selected.name;accountType.currentIndex=selected.administrator ? 1 : 0;resetPassword=false;confirmRemove=false;clearPasswords();}
    function syncUsers(){
        var signature=JSON.stringify(users);
        if(signature===usersSignature)return;
        usersSignature=signature;
        if(!users.some(row=>row.id===userId))userId=users.length ? users[0].id : -1;
        loadUser();
    }
    onUserIdChanged: loadUser()
    onVisibleChanged: if(!visible)clearPasswords()
    Component.onCompleted: {syncUsers();DesktopTools.refreshSystem(section);}
    Component.onDestruction:clearPasswords()
    Connections {target:DesktopTools;ignoreUnknownSignals:true;function onChanged(){administration.syncUsers();}}
    RowLayout {
        Layout.fillWidth:true
        Text {Layout.fillWidth:true;text:administration.section==="users" ? "Users and passwords" : "Date and time";color:Theme.text;font.pixelSize:Theme.fontSize(14)}
        OrbitButton {text:"Refresh";quiet:true;enabled:!administration.state.busy;implicitHeight:28;onClicked:DesktopTools.refreshSystem(administration.section)}
    }
    Text {visible:!!administration.state.error;Layout.fillWidth:true;text:administration.state.error || "";color:Theme.accent;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap;textFormat:Text.PlainText}
    Text {visible:administration.state.busy;Layout.fillWidth:true;text:"Waiting for the system…";color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
    ColumnLayout {
        visible:administration.section==="users";Layout.fillWidth:true;spacing:8
        RowLayout {
            Layout.fillWidth:true
            SettingsChoice {
                objectName:"systemUserPicker";Layout.fillWidth:true;Accessible.name:"User account"
                enabled:!administration.state.busy && !administration.adding
                model:administration.users.map(row=>({id:row.id,name:(row.displayName || row.name)+" · "+row.name+(row.current ? " · You" : "")}))
                currentIndex:model.findIndex(row=>row.id===administration.userId)
                onActivated:index=>administration.userId=model[index].id
            }
            OrbitButton {objectName:"systemUserAdd";text:administration.adding ? "Cancel" : "Add user";implicitHeight:32;enabled:!administration.state.busy;onClicked:{administration.adding=!administration.adding;administration.clearPasswords();}}
        }
        ColumnLayout {
            visible:!administration.adding && administration.selected.id>=0;Layout.fillWidth:true;spacing:8
            Text {Layout.fillWidth:true;text:(administration.selected.administrator ? "Administrator" : "Standard user")+(administration.selected.locked ? " · Locked" : "")+(administration.selected.loggedIn ? " · Signed in" : "");color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            SettingsGroup {
                title:"Profile"
                OrbitField {id:displayName;objectName:"systemUserDisplayName";Layout.fillWidth:true;placeholderText:"Display name";implicitHeight:34;maximumLength:80;enabled:!administration.state.busy}
                SettingsChoice {id:accountType;objectName:"systemUserAccountType";Layout.fillWidth:true;Accessible.name:"Account type";model:[{name:"Standard user"},{name:"Administrator"}];enabled:!administration.state.busy && !administration.selected.current}
                OrbitButton {objectName:"systemUserSave";text:"Save profile";Layout.fillWidth:true;implicitHeight:30;enabled:!administration.state.busy;onClicked:DesktopTools.saveSystemUser(administration.userId,displayName.text,accountType.currentIndex===1)}
            }
            OrbitButton {objectName:"systemUserOwnPassword";visible:administration.selected.current;text:"Change my password…";Layout.fillWidth:true;enabled:!administration.state.busy;onClicked:DesktopTools.changeMyPassword()}
            Text {visible:administration.selected.current;Layout.fillWidth:true;text:"A terminal opens for the system’s current and new password prompts.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
            OrbitButton {objectName:"systemUserResetPassword";visible:!administration.selected.current;text:administration.resetPassword ? "Cancel password reset" : "Set password…";Layout.fillWidth:true;enabled:!administration.state.busy;onClicked:{administration.resetPassword=!administration.resetPassword;administration.clearPasswords();}}
            SettingsGroup {
                visible:administration.resetPassword && !administration.selected.current;title:"New password"
                OrbitField {id:resetValue;objectName:"systemUserResetValue";Layout.fillWidth:true;placeholderText:"New password";echoMode:TextInput.Password;implicitHeight:34;maximumLength:1024;enabled:!administration.state.busy}
                OrbitField {id:resetConfirm;objectName:"systemUserResetConfirm";Layout.fillWidth:true;placeholderText:"Repeat password";echoMode:TextInput.Password;implicitHeight:34;maximumLength:1024;enabled:!administration.state.busy}
                Text {Layout.fillWidth:true;text:"Setting a password unlocks this account. Existing encrypted keyrings keep their old password.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
                OrbitButton {objectName:"systemUserResetApply";text:"Set password";Layout.fillWidth:true;implicitHeight:30;enabled:!administration.state.busy && resetValue.text.length>=8 && resetValue.text===resetConfirm.text;onClicked:{DesktopTools.resetSystemPassword(administration.userId,resetValue.text,resetConfirm.text);administration.clearPasswords();}}
            }
            OrbitButton {objectName:"systemUserRemove";visible:!administration.selected.current && !administration.confirmRemove;text:"Remove account…";Layout.fillWidth:true;enabled:!administration.state.busy && !!administration.selected.sessionsKnown && !administration.selected.loggedIn;onClicked:administration.confirmRemove=true}
            SettingsGroup {
                visible:administration.confirmRemove;title:"Remove this account?"
                Text {Layout.fillWidth:true;text:"This removes "+administration.selected.name+" from sign-in. Its home directory and files are kept.";color:Theme.text;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap;textFormat:Text.PlainText}
                RowLayout {
                    Layout.fillWidth:true
                    OrbitButton {text:"Cancel";Layout.fillWidth:true;implicitHeight:30;onClicked:administration.confirmRemove=false}
                    OrbitButton {objectName:"systemUserRemoveConfirm";text:"Remove account";Layout.fillWidth:true;implicitHeight:30;enabled:!administration.state.busy;onClicked:{DesktopTools.removeSystemUser(administration.userId);administration.confirmRemove=false;}}
                }
            }
        }
        SettingsGroup {
            visible:administration.adding;title:"New account"
            OrbitField {id:newName;objectName:"systemUserNewLogin";Layout.fillWidth:true;placeholderText:"Login name";implicitHeight:34;maximumLength:31;enabled:!administration.state.busy}
            OrbitField {id:newDisplay;objectName:"systemUserNewDisplay";Layout.fillWidth:true;placeholderText:"Display name";implicitHeight:34;maximumLength:80;enabled:!administration.state.busy}
            SettingsChoice {id:newType;objectName:"systemUserNewType";Layout.fillWidth:true;Accessible.name:"New account type";model:[{name:"Standard user"},{name:"Administrator"}];enabled:!administration.state.busy}
            OrbitField {id:newPassword;objectName:"systemUserNewPassword";Layout.fillWidth:true;placeholderText:"Password (at least 8 characters)";echoMode:TextInput.Password;implicitHeight:34;maximumLength:1024;enabled:!administration.state.busy}
            OrbitField {id:newConfirm;objectName:"systemUserNewConfirm";Layout.fillWidth:true;placeholderText:"Repeat password";echoMode:TextInput.Password;implicitHeight:34;maximumLength:1024;enabled:!administration.state.busy}
            OrbitButton {objectName:"systemUserCreate";text:"Create account";Layout.fillWidth:true;implicitHeight:30;enabled:!administration.state.busy && newName.text.length>0 && newDisplay.text.length>0 && newPassword.text.length>=8 && newPassword.text===newConfirm.text;onClicked:{DesktopTools.createSystemUser(newName.text,newDisplay.text,newPassword.text,newConfirm.text,newType.currentIndex===1);administration.clearPasswords();}}
        }
    }
    ColumnLayout {
        visible:administration.section==="datetime";Layout.fillWidth:true;spacing:8
        Text {Layout.fillWidth:true;text:"Current time zone: "+(administration.state.timezone || "Not available");color:Theme.text;font.pixelSize:Theme.fontSize(12);wrapMode:Text.Wrap}
        SettingsGroup {
            title:"Time zone"
            OrbitField {id:zoneSearch;objectName:"systemTimezoneSearch";Layout.fillWidth:true;placeholderText:"Find a city or region";implicitHeight:34;enabled:!administration.state.busy}
            SettingsChoice {id:zonePicker;objectName:"systemTimezonePicker";Layout.fillWidth:true;Accessible.name:"Time zone";model:administration.zoneRows;enabled:!administration.state.busy;currentIndex:Math.max(0,model.findIndex(row=>row.id===administration.state.timezone))}
            OrbitButton {objectName:"systemTimezoneApply";text:"Apply time zone";Layout.fillWidth:true;implicitHeight:30;enabled:!administration.state.busy && zonePicker.currentIndex>=0 && administration.zoneRows.length>0;onClicked:DesktopTools.setSystemTimezone(administration.zoneRows[zonePicker.currentIndex].id)}
        }
        SettingsGroup {
            title:"Clock"
            SettingRow {label:"Automatic date and time";SettingToggle {objectName:"systemAutomaticTime";label:"Automatic date and time";checked:!!administration.state.ntp;enabled:!administration.state.busy && !!administration.state.canNtp;onClicked:DesktopTools.setSystemNtp(checked)}}
            Text {Layout.fillWidth:true;text:administration.state.ntp ? (administration.state.synchronized ? "Time is synchronized." : "Waiting for network time synchronization.") : "Automatic time is off.";color:Theme.muted;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
            OrbitField {id:manualClock;objectName:"systemManualTime";visible:!administration.state.ntp;Layout.fillWidth:true;placeholderText:"UTC: YYYY-MM-DD HH:MM";accessibleLabel:"UTC date and time";implicitHeight:34;maximumLength:16;enabled:!administration.state.busy && administration.state.clockAvailable}
            OrbitButton {objectName:"systemManualTimeApply";visible:!administration.state.ntp;text:"Set UTC date and time";Layout.fillWidth:true;implicitHeight:30;enabled:!administration.state.busy && administration.state.clockAvailable && manualClock.text.length===16;onClicked:DesktopTools.setSystemTime(manualClock.text)}
        }
    }
}
