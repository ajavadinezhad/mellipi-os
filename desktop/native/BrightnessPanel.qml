import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
SettingsGroup {
    id: brightness;objectName: "brightnessPanel"
    property bool displayOptions: false
    property bool showDisplayOptions: true
    title: "Brightness"
    SettingRow {
        label: Brightness.state.available ? Brightness.state.name : "Display"
        Text { text: Brightness.state.available ? Brightness.state.percent+"%" : "Unavailable";color: Theme.muted;font.pixelSize: Theme.fontSize(11) }
    }
    OrbitSlider {
        id: brightnessSlider;objectName:"brightnessSlider";property bool userAdjusting: false
        Accessible.name: "Display brightness"
        visible: Brightness.state.available;Layout.fillWidth: true;Layout.leftMargin: 6;Layout.rightMargin: 6
        from: 1;to: 100;stepSize: 1;value: Brightness.state.percent;enabled: Brightness.state.available
        onMoved: {userAdjusting=true;brightnessTimer.restart();}
        onPressedChanged: if(!pressed && userAdjusting){brightnessTimer.stop();Brightness.setBrightness(Math.round(value));userAdjusting=false;}
        Timer { id: brightnessTimer;interval: 120;onTriggered: {Brightness.setBrightness(Math.round(brightnessSlider.value));if(!brightnessSlider.pressed)brightnessSlider.userAdjusting=false;} }
    }
    Text { visible: !Brightness.state.available;Layout.fillWidth: true;Layout.margins: 6;text: Brightness.state.reason || "Brightness controls unavailable";color: Theme.faint;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap;maximumLineCount: 3;elide: Text.ElideRight;textFormat: Text.PlainText }
    OrbitButton { objectName: "displayOptionsToggle";visible: brightness.showDisplayOptions;text: "Display options "+(brightness.displayOptions ? "⌃" : "⌄");quiet: true;implicitHeight: 26;onClicked: brightness.displayOptions=!brightness.displayOptions }
    ColumnLayout {
        visible: brightness.showDisplayOptions && brightness.displayOptions;Layout.fillWidth: true;Layout.margins: 3;spacing: 4
        OrbitButton { text: "Detect external displays…";quiet: true;implicitHeight: 26;enabled: !Brightness.state.busy;onClicked: Brightness.discoverExternal() }
        Flow {
            Layout.fillWidth: true;Layout.preferredHeight: childrenRect.height;spacing: 4
            Repeater {
                model: Brightness.externalDisplays
                OrbitButton { required property var modelData;text: modelData.name.slice(0,20);quiet: Brightness.state.externalId!==modelData.id;implicitHeight: 26;hint: modelData.name;enabled: !Brightness.state.busy;onClicked: Brightness.selectExternal(modelData.id) }
            }
        }
        OrbitButton { visible: Brightness.state.backend==="ddc";text: "Reset display selection";quiet: true;implicitHeight: 26;enabled: !Brightness.state.busy;onClicked: Brightness.selectExternal(0) }
    }
}
