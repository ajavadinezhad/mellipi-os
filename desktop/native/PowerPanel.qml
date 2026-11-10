import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: panel;objectName: "powerProfilesPanel"
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    Component.onCompleted: PowerProfiles.refresh()
    ColumnLayout {
        id: content;width: panel.availableWidth;spacing: 10
        SettingsGroup {
            title: "System power mode"
            Text {Layout.fillWidth: true;Layout.margins: 6;text: "Choose how the computer balances performance and battery use.";wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
            Repeater {
                model: PowerProfiles.profiles
                OrbitButton {
                    required property var modelData
                    objectName: "systemPower_"+modelData.name
                    Layout.fillWidth: true;implicitHeight: Theme.fontSize(34);text: modelData.label+(PowerProfiles.state.active===modelData.name ? " · Active" : "")
                    accent: PowerProfiles.state.active===modelData.name;quiet: !accent;enabled: PowerProfiles.state.available && !PowerProfiles.state.busy
                    Accessible.name: modelData.label+(accent ? ", active system power mode" : ", system power mode")
                    onClicked: PowerProfiles.setProfile(modelData.name)
                }
            }
            Text {visible: (PowerProfiles.state.degraded || "").length>0;Layout.fillWidth: true;Layout.margins: 6;text: "Performance limited: "+PowerProfiles.state.degraded;wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText}
        }
        Text {objectName: "powerProfileError";visible: text.length>0;text: PowerProfiles.state.error || "";Layout.fillWidth: true;wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11);textFormat: Text.PlainText}
        Text {text: "This changes the computer’s power use. Shell rendering in Appearance controls desktop effects separately.";Layout.fillWidth: true;wrapMode: Text.Wrap;color: Theme.faint;font.pixelSize: Theme.fontSize(10)}
        OrbitButton {objectName: "powerProfilesRefresh";text: "Refresh modes";quiet: true;implicitHeight: Theme.fontSize(28);enabled: !PowerProfiles.state.busy;onClicked: PowerProfiles.refresh()}
    }
}
