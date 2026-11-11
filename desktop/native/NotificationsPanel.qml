import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: panel;objectName: "notificationsPanel";spacing: 12
    Component.onCompleted: Qt.callLater(function(){if(dndToggle.visible)dndToggle.forceActiveFocus(Qt.TabFocusReason);})
    RowLayout {
        Layout.fillWidth: true
        OrbitButton {id:dndToggle;objectName:"notificationDndToggle"; text: System.doNotDisturb ? "DND on" : "Do not disturb";accent: System.doNotDisturb;onClicked: System.setDnd(!System.doNotDisturb) }
        Item { Layout.fillWidth: true }
        OrbitButton { text: "Clear";quiet: true;enabled: System.notifications.length>0;onClicked: System.clearNotifications() }
    }
    Text { visible: !System.values.notificationServer;text: "Another notification service is active.";color: Theme.faint;font.pixelSize: Theme.fontSize(10);Layout.fillWidth: true;wrapMode: Text.Wrap }
    ListView {
        id: list;objectName: "notificationList";Layout.fillWidth: true;Layout.fillHeight: true;clip: true;spacing: 8;reuseItems: true;model: System.notifications
        keyNavigationEnabled: true;activeFocusOnTab: true
        Keys.onReturnPressed: if(currentItem)currentItem.activate()
        Keys.onEnterPressed: if(currentItem)currentItem.activate()
        Keys.onSpacePressed: if(currentItem)currentItem.activate()
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
            function activate(){Orbit.dismiss();System.activateNotification(modelData.id);}
            MouseArea { anchors.fill: parent;cursorShape: Qt.PointingHandCursor;onClicked: {list.currentIndex=index;noteCard.activate();} }
            Column {
                id: noteColumn;x: 12;y: 12;width: parent.width-24;spacing: 6
                RowLayout {
                    width: parent.width;height: dismissButton.implicitHeight
                    Text { text: modelData.app;Layout.fillWidth: true;elide: Text.ElideRight;color: Theme.faint;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText }
                    IconButton {
                        id: dismissButton;objectName: "notificationDismiss"+index
                        iconName: "close";hint: "Dismiss "+modelData.summary
                        glyphColor: Theme.muted
                        onClicked: System.dismissNotification(modelData.id)
                    }
                }
                Text { text: modelData.summary;color: Theme.text;font.pixelSize: Theme.fontSize(12);width: parent.width;wrapMode: Text.Wrap;textFormat: Text.PlainText }
                Text { text: modelData.body;color: Theme.muted;font.pixelSize: Theme.fontSize(11);width: parent.width;wrapMode: Text.Wrap;maximumLineCount: 3;elide: Text.ElideRight;textFormat: Text.PlainText }
                Column {
                    width: parent.width;spacing: 4;visible: actionRepeater.count>0
                    Repeater {
                        id: actionRepeater
                        model: (modelData.actions || []).filter(a => a.key!=="default")
                        OrbitButton { required property var modelData;text: modelData.label;Accessible.name: text+", "+noteCard.modelData.summary;height: Math.max(26,Theme.fontSize(12)+12);width: parent.width;onClicked: System.invokeNotificationAction(noteCard.modelData.id,modelData.key) }
                    }
                }
            }
        }
        Text { anchors.centerIn: parent;visible: list.count===0;text: "No notifications";font.pixelSize: Theme.fontSize(12);color: Theme.muted }
    }
}
