import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: panel;objectName: "lockPanel"
    Component.onCompleted: Idle.apply()
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    ColumnLayout {
        id: content;width: panel.availableWidth;spacing: 10
        SettingsGroup {
            title: "Automatic lock"
            SettingRow {label: "Lock when idle";SettingToggle {objectName: "idleLockToggle";label: "Automatically lock when idle";checked: Orbit.appearance.idleLockEnabled;onClicked: Orbit.setPreference("idleLockEnabled",checked)}}
            SettingRow {
                label: "Lock after";enabled: Orbit.appearance.idleLockEnabled
                OrbitField {objectName: "idleLockMinutes";implicitWidth: 60;implicitHeight: 28;text: Orbit.appearance.idleLockMinutes;inputMethodHints: Qt.ImhDigitsOnly;validator: IntValidator {bottom: 1;top: 120} Accessible.name: "Minutes before automatic lock";onEditingFinished: if(acceptableInput)Orbit.setPreference("idleLockMinutes",parseInt(text))}
                Text {text: "minutes";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
            }
            SettingRow {label: "Lock before sleep";SettingToggle {objectName: "lockBeforeSleepToggle";label: "Lock before system sleep";checked: Orbit.appearance.lockBeforeSleep;onClicked: Orbit.setPreference("lockBeforeSleep",checked)}}
        }
        SettingsGroup {
            title: "Display idle"
            SettingRow {
                label: "Turn display off after"
                OrbitField {objectName: "displayOffMinutes";implicitWidth: 60;implicitHeight: 28;text: Orbit.appearance.displayOffMinutes;inputMethodHints: Qt.ImhDigitsOnly;validator: IntValidator {bottom: 0;top: 120} Accessible.name: "Minutes before display turns off, zero disables";onEditingFinished: if(acceptableInput)Orbit.setPreference("displayOffMinutes",parseInt(text))}
                Text {text: "min";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
            }
            Text {Layout.fillWidth: true;Layout.margins: 6;text: "0 keeps the display on. Moving the pointer or pressing a key wakes it.";wrapMode: Text.Wrap;color: Theme.faint;font.pixelSize: Theme.fontSize(10)}
            Text {visible: Orbit.appearance.idleLockEnabled && Orbit.appearance.displayOffMinutes>0 && Orbit.appearance.displayOffMinutes<=Orbit.appearance.idleLockMinutes;Layout.fillWidth: true;Layout.margins: 6;text: "The display will turn off five seconds after the lock timer, so locking happens first.";wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(10)}
        }
        Text {Layout.fillWidth: true;text: Idle.state.error || (!Idle.state.available ? "Automatic locking requires the system screen-lock prerequisites. Preview sessions do not start idle timers." : Idle.state.running ? "Idle policy is active. Changes restart its timer; they do not lock the screen immediately." : "Idle timers are off.");wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText}
        Text {Layout.fillWidth: true;text: "To unlock: type your login password, then press Enter. Esc clears a mistyped password.";wrapMode: Text.Wrap;color: Theme.faint;font.pixelSize: Theme.fontSize(10)}
    }
}
