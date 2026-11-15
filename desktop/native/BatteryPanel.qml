import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: battery
    readonly property bool present: Power.state.batteryPresent || System.values.batteryPresent
    readonly property var limitChoices: [{label:"60%",value:60},{label:"80%",value:80},{label:"100%",value:100}]
    spacing: 12
    SettingsGroup {
        title: "System battery"
        SettingRow {
            label: battery.present ? "Charge" : "No battery detected"
            Text { visible: battery.present;text: Power.state.percentageAvailable ? Power.state.batteryPercent+"%" : System.values.batteryPresent ? System.values.batteryPercent+"%" : "Unavailable";color: Theme.text;font.pixelSize: Theme.fontSize(14) }
        }
        SettingRow { visible: Power.state.batteryPresent;label: "Status";Text { text: Power.state.charging ? "Charging" : "Not charging";color: Theme.muted;font.pixelSize: Theme.fontSize(11) } }
    }
    SettingsGroup {
        title: "Charging limit"
        visible: battery.present
        SettingRow {
            label: "Stop charging at"
            SettingsSegments {objectName:"chargeLimitOptions";
                enabled: Power.state.chargeLimitSupported && Power.state.chargeLimitWritable && !Power.state.busy
                value: Power.state.chargeLimit;options: battery.limitChoices
                onSelected: value => Power.setChargeLimit(value)
            }
        }
        SettingRow { visible: Power.state.chargeLimitSupported && !battery.limitChoices.some(choice => choice.value===Power.state.chargeLimit);label: "Current limit";Text { text: Power.state.chargeLimit+"%";color: Theme.muted;font.pixelSize: Theme.fontSize(11) } }
        RowLayout {
            visible: Power.batteries.length>1;Layout.fillWidth: true;Layout.margins: 4
            Repeater { model: Power.batteries;OrbitButton { required property var modelData;text: modelData.name;quiet: Power.state.selectedBattery!==modelData.name;implicitHeight: 28;onClicked: Power.selectBattery(modelData.name) } }
        }
    }
    OrbitButton {visible:Power.state.chargeLimitPersistenceAvailable===true;text:"Stop restoring at startup…";quiet:true;enabled:!Power.state.busy;hint:"Keep the current limit and remove its saved startup setting";onClicked:Power.forgetChargeLimit()}
    Text { visible: Power.state.batteryPresent && text.length>0;Layout.fillWidth: true;text: Power.state.reason || "";wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11);textFormat: Text.PlainText }
    Item { Layout.fillHeight: true }
}
