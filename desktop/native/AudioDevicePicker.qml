import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: picker
    property var devices: []
    property string selectedName: ""
    property string chooseLabel: "Choose device"
    property string emptyLabel: "No device available"
    property string accessibleLabel: "Audio device"
    property bool expanded: false
    property int visibleChoices: 3
    signal toggled()
    signal selected(string name)
    Layout.fillWidth: true;spacing: 2
    OrbitButton {
        id: toggle
        objectName: picker.objectName+"Toggle"
        Layout.fillWidth: true;implicitHeight: 30;quiet: true
        text: {
            for(var i=0;i<picker.devices.length;i++)if(picker.devices[i].name===picker.selectedName)return picker.devices[i].description;
            return picker.devices.length ? picker.chooseLabel : picker.emptyLabel;
        }
        hint: text;Accessible.name: picker.accessibleLabel+": "+text
        contentItem: Item {
            implicitWidth: deviceName.implicitWidth+24;implicitHeight: 16
            Text {
                id: deviceName;objectName: picker.objectName+"Name"
                anchors.left: parent.left;anchors.right: indicator.left;anchors.rightMargin: 8;anchors.verticalCenter: parent.verticalCenter
                text: toggle.text;font: toggle.font;color: toggle.enabled ? Theme.text : Theme.disabled
                elide: Text.ElideRight;textFormat: Text.PlainText
            }
            Canvas {
                id: indicator;objectName: picker.objectName+"Indicator"
                anchors.right: parent.right;anchors.verticalCenter: parent.verticalCenter;width: 12;height: 12
                property bool up: picker.expanded
                property color ink: toggle.enabled ? Theme.muted : Theme.disabled
                onUpChanged: requestPaint();onInkChanged: requestPaint()
                onPaint: {var c=getContext("2d");c.clearRect(0,0,width,height);c.strokeStyle=ink;c.lineWidth=1.5;c.lineCap="round";c.lineJoin="round";c.beginPath();c.moveTo(2,up ? 8 : 4);c.lineTo(6,up ? 4 : 8);c.lineTo(10,up ? 8 : 4);c.stroke();}
            }
        }
        enabled: picker.devices.length>0
        onClicked: picker.toggled()
    }
    ListView {
        id: choices
        objectName: picker.objectName+"List"
        Layout.fillWidth: true;Layout.preferredHeight: visible ? Math.min(count,picker.visibleChoices)*30 : 0
        visible: picker.expanded;clip: true;boundsBehavior: Flickable.StopAtBounds
        model: picker.devices;interactive: count>picker.visibleChoices
        ScrollBar.vertical: ScrollBar { policy: choices.interactive ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }
        delegate: OrbitButton {
            id: choice
            objectName: picker.objectName+"Choice"+index
            width: ListView.view.width;height: 30;implicitHeight: 30
            text: modelData.description;hint: modelData.available===false ? "Device unplugged" : modelData.description
            enabled: modelData.available!==false
            readonly property bool selectedDevice: modelData.name===picker.selectedName
            quiet: true
            Accessible.name: text+(selectedDevice ? ", selected" : "")
            contentItem: Item {
                implicitWidth: choiceName.implicitWidth+24;implicitHeight: 16
                Text {
                    id: choiceName;anchors.left: parent.left;anchors.right: selection.left;anchors.rightMargin: 8;anchors.verticalCenter: parent.verticalCenter
                    text: choice.text;font: choice.font;color: choice.selectedDevice ? Theme.text : Theme.muted;elide: Text.ElideRight;textFormat: Text.PlainText
                }
                Canvas {
                    id: selection;anchors.right: parent.right;anchors.verticalCenter: parent.verticalCenter;width: 12;height: 12;visible: choice.selectedDevice
                    property color ink: Theme.accent
                    onInkChanged: requestPaint()
                    onPaint: {var c=getContext("2d");c.clearRect(0,0,width,height);c.strokeStyle=ink;c.lineWidth=1.5;c.lineCap="round";c.lineJoin="round";c.beginPath();c.moveTo(1,6);c.lineTo(4.5,9.5);c.lineTo(11,2.5);c.stroke();}
                }
            }
            onClicked: picker.selected(modelData.name)
        }
    }
}
