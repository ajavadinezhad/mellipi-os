import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: session;objectName: "sessionPanel";spacing: 10
    property bool showAccountActions: true
    property bool confirmSleep: false
    SettingsGroup {
        visible: session.showAccountActions
        title: "Your session"
        RowLayout {
            Layout.fillWidth: true;spacing: 5
            SessionActionButton {objectName: "sessionLock";iconName: "lock";text: "Lock";Layout.fillWidth: true;Layout.minimumWidth: 0;hint: "Lock the screen and keep your apps open";onClicked: Orbit.activateSystemAction("lock")}
            SessionActionButton {objectName: "sessionSwitchUser";iconName: "switch-user";text: "Switch user";Layout.fillWidth: true;Layout.minimumWidth: 0;enabled: Orbit.canSwitchUser===true;hint: enabled ? "Lock this session and return to the login screen" : "Switching users requires an Abstract login session and a supported login screen";onClicked: Orbit.switchUser()}
            SessionActionButton {objectName: "sessionLogout";iconName: "logout";text: Orbit.isWayland ? "Log out…" : "Exit Abstract…";Layout.fillWidth: true;Layout.minimumWidth: 0;hint: "Review open apps before leaving";onClicked: Orbit.activateSystemAction("logout")}
        }
    }
    SettingsGroup {
        title: "Power"
        RowLayout {
            Layout.fillWidth: true;spacing: 5
            SessionActionButton {objectName: "sessionSleep";iconName: "sleep";text: "Sleep…";Layout.fillWidth: true;Layout.minimumWidth: 0;hint: "Suspend this PC and keep your apps open";onClicked: session.confirmSleep=true}
            SessionActionButton {objectName: "sessionRestart";iconName: "restart";text: "Restart…";Layout.fillWidth: true;Layout.minimumWidth: 0;hint: "Review open apps before restarting this PC";onClicked: Orbit.activateSystemAction("reboot")}
            SessionActionButton {objectName: "sessionShutdown";iconName: "shutdown";text: "Shut down…";Layout.fillWidth: true;Layout.minimumWidth: 0;hint: "Review open apps before turning off this PC";onClicked: Orbit.activateSystemAction("shutdown")}
        }
        ColumnLayout {
            visible: session.confirmSleep;Layout.fillWidth: true;spacing: 6
            Text {Layout.fillWidth: true;text: "Put this PC to sleep? Your apps stay open.";wrapMode: Text.Wrap;color: Theme.text;font.pixelSize: Theme.fontSize(11)}
            RowLayout {
                Layout.fillWidth: true;spacing: 5
                OrbitButton {objectName: "sessionSleepConfirm";text: "Sleep now";accent: true;Layout.fillWidth: true;implicitHeight: 30;onClicked: {session.confirmSleep=false;System.power("suspend");}}
                OrbitButton {objectName: "sessionSleepCancel";text: "Cancel";quiet: true;Layout.fillWidth: true;implicitHeight: 30;onClicked: session.confirmSleep=false}
            }
        }
    }
}
