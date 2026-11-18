import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: panel;objectName: "notificationsPanel";spacing: 12
    Component.onCompleted: Qt.callLater(function(){if(dndToggle.visible)dndToggle.forceActiveFocus(Qt.TabFocusReason);})
    RowLayout {
        Layout.fillWidth: true
        IconButton {id:dndToggle;objectName:"notificationDndToggle";iconName: "bell-off";hint: System.doNotDisturb ? "Turn off Do Not Disturb" : "Turn on Do Not Disturb";Accessible.checkable: true;Accessible.checked: System.doNotDisturb;accent: System.doNotDisturb;onClicked: System.setDnd(!System.doNotDisturb) }
        Item { Layout.fillWidth: true }
        OrbitButton { text: "Clear";Accessible.name:"Clear all notifications";quiet: true;enabled: System.notifications.length>0;onClicked: System.clearNotifications() }
    }
    Text { visible: !System.values.notificationServer;text: "Another notification service is active.";color: Theme.faint;font.pixelSize: Theme.fontSize(10);Layout.fillWidth: true;wrapMode: Text.Wrap }
    ListView {
        id: list;objectName: "notificationList";Layout.fillWidth: true;Layout.fillHeight: true;clip: true;spacing: 8;reuseItems: true;model: System.notifications
        keyNavigationEnabled: true;activeFocusOnTab: true
        Keys.onReturnPressed: if(currentItem)currentItem.activate()
        Keys.onEnterPressed: if(currentItem)currentItem.activate()
        Keys.onSpacePressed: if(currentItem)currentItem.activate()
        Keys.onPressed: event => {
            if(event.key===Qt.Key_Menu || (event.key===Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))){
                if(currentItem){currentItem.openOptions();event.accepted=true;}
            }
        }
        Keys.onDeletePressed: if(currentItem)System.dismissNotification(currentItem.modelData.id)
        Component.onCompleted: if(count>0)currentIndex=0
        onCountChanged: if(currentIndex<0 && count>0)currentIndex=0
        delegate: Rectangle {
            id: noteCard;required property var modelData;required property int index;width: ListView.view.width;height: noteColumn.height+24;color: Theme.surface;radius: Theme.corner(9)
            objectName: "notificationCard"+index
            border.color: ListView.isCurrentItem && list.activeFocus ? Theme.focusColor : Theme.border
            border.width: ListView.isCurrentItem && list.activeFocus ? 2 : 0
            Accessible.role: Accessible.Button
            Accessible.name: modelData.app+", "+modelData.summary
            Accessible.description: modelData.body
            Accessible.onPressAction: activate()
            readonly property var actions: (modelData.actions || []).filter(a => a.key!=="default")
            function openOptions(){list.currentIndex=index;noteMenu.popup();}
            function activate(){Orbit.dismiss();System.activateNotification(modelData.id);}

            Column {
                id: noteColumn;x: 12;y: 12;width: parent.width-24;spacing: 6
                RowLayout {
                    width: parent.width;height: dismissButton.implicitHeight
                    Text { text: modelData.app;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.faint;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText }
                    IconButton {
                        id:dismissButton;objectName:"notificationDismiss"+index
                        iconName:"more";hint:"Notification options";glyphColor:Theme.muted
                        onClicked:noteCard.openOptions()
                        Menu {
                            id:noteMenu
                            Instantiator {
                                model:noteCard.actions.slice(1)
                                delegate:MenuItem {
                                    required property var modelData
                                    text:modelData.label
                                    onTriggered:System.invokeNotificationAction(noteCard.modelData.id,modelData.key)
                                }
                                onObjectAdded:(i,item)=>noteMenu.insertItem(i,item)
                                onObjectRemoved:(i,item)=>noteMenu.removeItem(item)
                            }
                            MenuItem {text:"Dismiss notification";onTriggered:System.dismissNotification(noteCard.modelData.id)}
                        }
                    }
                }
                Text {
                    text:modelData.summary;color:Theme.text;font.pixelSize:Theme.fontSize(12)
                    width:parent.width;wrapMode:Text.Wrap;textFormat:Text.PlainText
                    MouseArea {anchors.fill:parent;cursorShape:Qt.PointingHandCursor;onClicked:{list.currentIndex=index;noteCard.activate();}}
                }
                Text {
                    text:modelData.body;color:Theme.muted;font.pixelSize:Theme.fontSize(11)
                    width:parent.width;wrapMode:Text.Wrap;maximumLineCount:3;elide:Text.ElideRight;textFormat:Text.PlainText
                    MouseArea {anchors.fill:parent;cursorShape:Qt.PointingHandCursor;onClicked:{list.currentIndex=index;noteCard.activate();}}
                }
                OrbitButton {
                    visible:noteCard.actions.length>0;width:Math.min(implicitWidth,parent.width)
                    text:visible ? noteCard.actions[0].label : ""
                    Accessible.name:text+", "+noteCard.modelData.summary
                    onClicked:System.invokeNotificationAction(noteCard.modelData.id,noteCard.actions[0].key)
                }
            }
        }
        Text { anchors.centerIn: parent;visible: list.count===0;text: "No notifications";font.pixelSize: Theme.fontSize(12);color: Theme.muted }
    }
}
