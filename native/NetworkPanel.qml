import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: panel;objectName: "networkPanel"
    property string selected: ""
    property string confirmForget: ""
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    Component.onCompleted: Network.refresh()
    ColumnLayout {
        id: content;width: panel.availableWidth;spacing: 10
        SettingsGroup {
            title: "Connections"
            RowLayout {
                Layout.fillWidth: true;Layout.margins: 5
                Text {text: "Wi-Fi, Ethernet & VPN";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true;elide: Text.ElideRight}
                IconButton {objectName: "networkRefresh";iconName:"refresh";hint:"Refresh connections";implicitWidth:Math.max(30,Theme.fontSize(28));implicitHeight:Math.max(30,Theme.fontSize(28));enabled: Network.state.available && !Network.state.busy;onClicked: Network.refresh()}
            }
            ListView {
                id: profiles;objectName: "networkConnections";model: Network.connections
                Layout.fillWidth: true;Layout.preferredHeight: count ? Math.min(count,4)*Theme.fontSize(64)+(panel.selected ? Theme.fontSize(panel.confirmForget ? 86 : 46) : 0) : 36
                clip: true;spacing: 4;cacheBuffer: 0;reuseItems: true;boundsBehavior: Flickable.StopAtBounds
                delegate: Rectangle {
                    id: card;required property var modelData;required property int index
                    objectName: "networkConnection_"+index
                    width: ListView.view.width;height: panel.selected===modelData.uuid ? Theme.fontSize(panel.confirmForget===modelData.uuid ? 144 : 104) : Theme.fontSize(58)
                    color: card.activeFocus ? Theme.hover : Theme.surface;border.color: card.activeFocus ? Theme.accent : "transparent";radius: Theme.corner(6)
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button;Accessible.name: modelData.name+", "+modelData.label+(modelData.active ? ", connected" : ", disconnected")
                    Accessible.onPressAction: panel.selected=panel.selected===modelData.uuid ? "" : modelData.uuid
                    Keys.onReturnPressed: panel.selected=panel.selected===modelData.uuid ? "" : modelData.uuid
                    Keys.onSpacePressed: panel.selected=panel.selected===modelData.uuid ? "" : modelData.uuid
                    MouseArea {anchors.fill: parent;onClicked: {card.forceActiveFocus();panel.selected=panel.selected===card.modelData.uuid ? "" : card.modelData.uuid;panel.confirmForget="";}}
                    ColumnLayout {
                        anchors.fill: parent;anchors.margins: 8;spacing: 5
                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                Layout.fillWidth: true;spacing: 2
                                Text {text: card.modelData.name;Layout.fillWidth: true;color: Theme.text;font.pixelSize: Theme.fontSize(12);elide: Text.ElideRight;textFormat: Text.PlainText}
                                Text {text: card.modelData.label+(card.modelData.device ? " · "+card.modelData.device : "");Layout.fillWidth: true;color: Theme.faint;font.pixelSize: Theme.fontSize(10);elide: Text.ElideRight;textFormat: Text.PlainText}
                            }
                            Text {text: card.modelData.active ? "Connected" : "Saved";color: card.modelData.active ? Theme.accent : Theme.muted;font.pixelSize: Theme.fontSize(10)}
                        }
                        RowLayout {
                            visible: panel.selected===card.modelData.uuid;Layout.fillWidth: true;spacing: 5
                            OrbitButton {objectName: "networkActivate_"+index;text: card.modelData.active ? "Disconnect" : "Connect";Layout.fillWidth: true;implicitHeight: Theme.fontSize(28);enabled: !Network.state.busy;onClicked: {panel.confirmForget="";if(card.modelData.active)Network.disconnect(card.modelData.uuid);else Network.activate(card.modelData.uuid);}}
                            OrbitButton {objectName: "networkForget_"+index;text: "Forget…";quiet: true;implicitHeight: Theme.fontSize(28);enabled: !Network.state.busy;onClicked: panel.confirmForget=card.modelData.uuid}
                        }
                        RowLayout {
                            visible: panel.confirmForget===card.modelData.uuid;Layout.fillWidth: true
                            Text {text: card.modelData.active ? "Forget and disconnect?" : "Remove saved settings?";color: Theme.muted;font.pixelSize: Theme.fontSize(10);Layout.fillWidth: true;wrapMode: Text.Wrap}
                            OrbitButton {objectName: "networkForgetConfirm_"+index;text: "Forget";implicitHeight: Theme.fontSize(26);enabled: !Network.state.busy;onClicked: {Network.forget(card.modelData.uuid);panel.confirmForget="";panel.selected="";}}
                            OrbitButton {text: "Cancel";quiet: true;implicitHeight: Theme.fontSize(26);onClicked: panel.confirmForget=""}
                        }
                    }
                }
                Text {anchors.centerIn: parent;visible: profiles.count===0;text: Network.state.busy ? "Loading connections…" : "No saved connections";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
            }
        }
        Text {objectName: "networkError";visible: text.length>0;text: Network.state.error || "";Layout.fillWidth: true;wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11);textFormat: Text.PlainText}
        OrbitButton {objectName: "networkAdvanced";text: "Advanced connection settings…";Layout.fillWidth: true;implicitHeight: Theme.fontSize(30);quiet: true;enabled: Network.state.advancedAvailable && !Network.state.busy;onClicked: {Orbit.dismiss();Network.openAdvanced();}}
        Text {text: "Create or edit VPN, Ethernet and enterprise Wi-Fi connections in the system connection editor. New Wi-Fi networks are available in Quick settings.";Layout.fillWidth: true;wrapMode: Text.Wrap;color: Theme.faint;font.pixelSize: Theme.fontSize(10)}
    }
}
