import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: panel;objectName: "screenshotPanel"
    function openDestination() {Orbit.dismiss();Screenshots.openFolder();}
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    ColumnLayout {
        id: content;width: panel.availableWidth;spacing: 12
        SettingsGroup {
            title: "Capture"
            RowLayout {
                Layout.fillWidth: true;Layout.margins: 4;spacing: 6
                OrbitButton { text: "Display";Layout.fillWidth: true;enabled: !Screenshots.state.busy && !Screenshots.state.selecting;onClicked: Screenshots.captureScreen() }
                OrbitButton { text: "Area";Layout.fillWidth: true;enabled: !Screenshots.state.busy && !Screenshots.state.selecting;onClicked: Screenshots.beginArea() }
                OrbitButton { text: "Window";Layout.fillWidth: true;enabled: !Screenshots.state.busy && !Screenshots.state.selecting;onClicked: Screenshots.captureWindow() }
            }
        }
        SettingsGroup {
            title: "Options"
            SettingRow {
                label: "Copy to clipboard"
                SettingToggle { label: "Copy screenshot to clipboard";checked: Screenshots.state.copyToClipboard;enabled: !Screenshots.state.busy;onToggled: Screenshots.setCopy(checked) }
            }
        }
        SettingsGroup {
            title: "Save destination"
            Text {
                id: destination;objectName: "screenshotDestination"
                text: Screenshots.state.destination || "";Layout.fillWidth: true;Layout.margins: 6
                color: Theme.accent;font.pixelSize: Theme.fontSize(11);font.underline: true;wrapMode: Text.WrapAnywhere;textFormat: Text.PlainText
                activeFocusOnTab: true
                Accessible.role: Accessible.Link;Accessible.name: "Open screenshots folder: "+text
                Accessible.onPressAction: panel.openDestination()
                Keys.onReturnPressed: panel.openDestination()
                Keys.onSpacePressed: panel.openDestination()
                MouseArea { anchors.fill: parent;cursorShape: Qt.PointingHandCursor;onClicked: panel.openDestination() }
            }
        }
        Text { text: "Capturing…";visible: Screenshots.state.busy;Layout.fillWidth: true;color: Theme.muted;font.pixelSize: Theme.fontSize(11) }
        Text { text: Screenshots.state.error || "";visible: text.length>0;Layout.fillWidth: true;wrapMode: Text.Wrap;color: Theme.text;font.pixelSize: Theme.fontSize(11);textFormat: Text.PlainText }
    }
}
