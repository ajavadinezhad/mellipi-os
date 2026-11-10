import QtQuick 2.15
import "."
Item {
    id: navigation
    property string currentView: "work"
    property bool narrow: false
    property bool carrying: false
    signal viewSelected(string view)
    signal sharedRequested()
    implicitWidth: narrow ? Math.max(61,Theme.fontSize(11)*4+14) : Math.max(91,Theme.fontSize(11)*5+16)
    implicitHeight: 250
    Rectangle {anchors.right: parent.right;width: 1;height: parent.height;color: Theme.border}
    Column {
        anchors.left: parent.left;anchors.right: parent.right;anchors.rightMargin: 9;spacing: 6
        Repeater {
            model: [{view:"work",label:"Work",number:"01",name:"foldWorkButton"},{view:"apps",label:"Open",number:"02",name:"foldAppsButton"},{view:"unfold",label:"Switch",number:"03",name:"foldUnfoldButton"}]
            OrbitButton {
                id: entry;required property var modelData
                objectName: modelData.name;width: parent.width;height: 53;padding: 7;quiet: true
                Accessible.name: modelData.label+(navigation.currentView===modelData.view ? ", selected" : "")
                contentItem: Column {
                    spacing: 5
                    Text {text: entry.modelData.number;font.pixelSize: Theme.fontSize(9);color: navigation.currentView===entry.modelData.view ? Theme.accent : Theme.faint}
                    Text {text: entry.modelData.label;font.pixelSize: Theme.fontSize(11);color: navigation.currentView===entry.modelData.view ? Theme.text : Theme.muted;elide: Text.ElideRight;width: entry.availableWidth}
                }
                background: Rectangle {
                    color: navigation.currentView===entry.modelData.view ? Theme.raised : entry.hovered || entry.activeFocus ? Theme.hover : "transparent"
                    border.color: entry.activeFocus ? Theme.focusColor : "transparent"
                    Rectangle {width: 2;height: parent.height;color: Theme.accent;visible: navigation.currentView===entry.modelData.view}
                }
                onClicked: {if(modelData.view==="shared")navigation.sharedRequested();else navigation.viewSelected(modelData.view);}
            }
        }
    }
    Text {anchors.bottom: parent.bottom;anchors.left: parent.left;anchors.right: parent.right;anchors.rightMargin: 8;visible: navigation.carrying;text: "ITEM\nHELD →";font.pixelSize: Theme.fontSize(9);font.letterSpacing: .5;color: Theme.accent;lineHeight: 1.4}
}
