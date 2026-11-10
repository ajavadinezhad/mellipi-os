import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: panel
    function memory(value) { return value>=1024 ? (value/1024).toFixed(1)+" GiB" : Math.round(value)+" MiB"; }
    spacing: 12
    ColumnLayout {
        Layout.fillWidth: true;Layout.fillHeight: false;spacing: 3
        Text { text: Usage.displayName;visible: text.length>0 && text!==Usage.username;color: Theme.text;font.pixelSize: Theme.fontSize(14);Layout.fillWidth: true;elide: Text.ElideRight;textFormat: Text.PlainText }
        Text { text: "Signed in as "+Usage.username;color: Theme.muted;font.pixelSize: Theme.fontSize(11);Layout.fillWidth: true;elide: Text.ElideRight;textFormat: Text.PlainText }
    }
    SettingsGroup {
        title: "System";Layout.fillHeight: false
        ColumnLayout {
            Layout.fillWidth: true;Layout.margins: 6;spacing: 12
            ColumnLayout {
                Layout.fillWidth: true;spacing: 5
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "CPU";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true }
                    Text { text: Usage.state.cpuReady ? Math.round(Usage.state.cpuPercent)+"%" : Usage.state.cpuAvailable ? "Measuring…" : "Unavailable";color: Theme.muted;font.pixelSize: Theme.fontSize(11) }
                }
                ProgressBar {
                    objectName: "cpuUsageBar"
                    Layout.fillWidth: true;Layout.preferredHeight: 5;from: 0;to: 100;value: Usage.state.cpuReady ? Usage.state.cpuPercent : 0
                    background: Rectangle { color: Theme.raised;radius: 2 }
                    contentItem: Item { Rectangle { width: parent.width*parent.parent.visualPosition;height: parent.height;color: Theme.accent;radius: 2 } }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true;spacing: 5
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Memory";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true }
                    Text { text: Usage.state.memoryReady ? Math.round(Usage.state.memoryPercent)+"%" : "Unavailable";color: Theme.muted;font.pixelSize: Theme.fontSize(11) }
                }
                ProgressBar {
                    objectName: "memoryUsageBar"
                    Layout.fillWidth: true;Layout.preferredHeight: 5;from: 0;to: 100;value: Usage.state.memoryPercent
                    background: Rectangle { color: Theme.raised;radius: 2 }
                    contentItem: Item { Rectangle { width: parent.width*parent.parent.visualPosition;height: parent.height;color: Theme.accent;radius: 2 } }
                }
                Text { text: panel.memory(Usage.state.memoryUsed)+" of "+panel.memory(Usage.state.memoryTotal);visible: Usage.state.memoryReady;color: Theme.faint;font.pixelSize: Theme.fontSize(10) }
            }
            ColumnLayout {
                Layout.fillWidth: true;spacing: 5
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Swap";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true }
                    Text { text: Usage.state.swapTotal>0 ? Math.round(Usage.state.swapPercent)+"%" : "None";color: Theme.muted;font.pixelSize: Theme.fontSize(11) }
                }
                ProgressBar {
                    objectName: "swapUsageBar"
                    visible: Usage.state.swapTotal>0;Layout.fillWidth: true;Layout.preferredHeight: 5;from: 0;to: 100;value: Usage.state.swapPercent
                    background: Rectangle { color: Theme.raised;radius: 2 }
                    contentItem: Item { Rectangle { width: parent.width*parent.parent.visualPosition;height: parent.height;color: Theme.accent;radius: 2 } }
                }
                Text { text: Usage.state.swapTotal>0 ? panel.memory(Usage.state.swapUsed)+" of "+panel.memory(Usage.state.swapTotal) : "No swap configured";color: Theme.faint;font.pixelSize: Theme.fontSize(10) }
            }
        }
    }
    Item { Layout.fillHeight: true }
    Text { visible: (Usage.state.error || "").length>0;text: Usage.state.error || "";color: Theme.faint;font.pixelSize: Theme.fontSize(10);Layout.fillWidth: true;wrapMode: Text.Wrap;textFormat: Text.PlainText }
}
