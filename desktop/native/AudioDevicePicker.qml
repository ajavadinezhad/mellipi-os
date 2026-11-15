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
    readonly property int rowHeight: Math.max(34,Theme.fontSize(12)+14)
    signal toggled()
    signal selected(string name)
    function focusChoice(start, step) {
        for (var i=start;i>=0 && i<devices.length;i+=step) {
            if (devices[i].available===false) continue;
            choices.positionViewAtIndex(i,ListView.Contain);
            choices.forceLayout();
            const row=choices.itemAtIndex(i);
            if(row) row.forceActiveFocus(Qt.TabFocusReason);
            return;
        }
    }
    Layout.fillWidth: true;spacing: 2
    OrbitButton {
        id: pickerToggle
        objectName: picker.objectName+"Toggle"
        Layout.fillWidth: true;implicitHeight: picker.rowHeight;quiet: true
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
                text: pickerToggle.text;font: pickerToggle.font;color: pickerToggle.enabled ? Theme.text : Theme.disabled
                elide: Text.ElideRight;textFormat: Text.PlainText
            }
            ControlMark {
                id: indicator;objectName: picker.objectName+"Indicator"
                anchors.right: parent.right;anchors.verticalCenter: parent.verticalCenter;width: 12;height: 12
                up: picker.expanded
                ink: pickerToggle.enabled ? Theme.muted : Theme.disabled
            }
        }
        background: ControlSurface {
            field: true;controlEnabled: pickerToggle.enabled;focused: pickerToggle.activeFocus
            pressed: pickerToggle.visuallyDown;hovered: pickerToggle.hovered
        }
        enabled: picker.devices.length>0
        onClicked: picker.toggled()
        Keys.onDownPressed: {
            if(!picker.expanded) picker.toggled();
            Qt.callLater(function() {
                var selected=picker.devices.findIndex(device=>device.name===picker.selectedName && device.available!==false);
                if(picker.expanded) picker.focusChoice(Math.max(0,selected),1);
            });
        }
        Keys.onEscapePressed: event => {
            event.accepted=picker.expanded;
            if(event.accepted) picker.toggled();
        }
    }
    ListView {
        id: choices
        objectName: picker.objectName+"List"
        Layout.fillWidth: true;Layout.preferredHeight: visible ? Math.min(count,picker.visibleChoices)*picker.rowHeight : 0
        visible: picker.expanded;clip: true;boundsBehavior: Flickable.StopAtBounds
        model: picker.devices;interactive: count>picker.visibleChoices
        ScrollBar.vertical: ScrollBar { policy: choices.interactive ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }
        delegate: OrbitButton {
            id: choice
            objectName: picker.objectName+"Choice"+index
            onActiveFocusChanged: if(activeFocus) {
                choices.currentIndex=index;
                choices.positionViewAtIndex(index,ListView.Contain);
            }
            Keys.onDownPressed: picker.focusChoice(index+1,1)
            Keys.onUpPressed: {
                if(index===0 || !picker.devices.slice(0,index).some(device=>device.available!==false))
                    pickerToggle.forceActiveFocus(Qt.TabFocusReason);
                else picker.focusChoice(index-1,-1);
            }
            Keys.onEscapePressed: {
                pickerToggle.forceActiveFocus(Qt.TabFocusReason);
                picker.toggled();
            }
            width: ListView.view.width;height: picker.rowHeight;implicitHeight: picker.rowHeight
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
                ControlMark {
                    id: selection;anchors.right: parent.right;anchors.verticalCenter: parent.verticalCenter;width: 12;height: 12;visible: choice.selectedDevice
                    check: true;ink: Theme.accentInk
                }
            }
            onClicked: {
                if(choice.activeFocus) pickerToggle.forceActiveFocus(Qt.TabFocusReason);
                picker.selected(modelData.name);
            }
        }
    }
}
