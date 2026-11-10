import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: picker
    property var windows: []
    property string query: ""
    signal selected(string ident)
    signal canceled()
    function choices() {var term=query.trim().toLowerCase();return windows.filter(w => !w.minimized && (!term || (w.title || "").toLowerCase().indexOf(term)>=0));}
    function chooseCurrent() {if(windowList.currentIndex>=0 && windowList.currentIndex<windowList.count)selected(String(windowList.model[windowList.currentIndex].id));}
    spacing: 10
    Text { text: "Choose the window to capture.";color: Theme.muted;font.pixelSize: Theme.fontSize(11);Layout.fillWidth: true }
    OrbitField {
        objectName: "windowCaptureSearch";Layout.fillWidth: true;implicitHeight: 34;placeholderText: "Find a window…";onTextChanged: picker.query=text
        Component.onCompleted: forceActiveFocus()
        Keys.onDownPressed: {windowList.forceActiveFocus();if(windowList.count>0)windowList.currentIndex=0;}
        Keys.onReturnPressed: picker.chooseCurrent()
    }
    ListView {
        id: windowList;objectName: "windowCaptureChoices";Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 120
        clip: true;spacing: 5;reuseItems: true;model: picker.choices()
        onCountChanged: if(count>0 && currentIndex<0)currentIndex=0
        Keys.onReturnPressed: picker.chooseCurrent()
        delegate: Rectangle {
            required property var modelData;required property int index
            width: windowList.width;height: 54;radius: Theme.corner(8);color: hit.containsMouse || (windowList.activeFocus && ListView.isCurrentItem) ? Theme.hover : Theme.surface
            border.color: Theme.border
            Image { x: 10;anchors.verticalCenter: parent.verticalCenter;width: 28;height: 28;source: "image://icons/"+(modelData.icon || "application-x-executable");sourceSize: Qt.size(32,32) }
            Text { x: 48;anchors.verticalCenter: parent.verticalCenter;width: parent.width-60;text: modelData.title || "Application window";color: Theme.text;font.pixelSize: Theme.fontSize(12);wrapMode: Text.Wrap;maximumLineCount: 2;elide: Text.ElideRight;textFormat: Text.PlainText }
            MouseArea { id: hit;anchors.fill: parent;hoverEnabled: true;onClicked: picker.selected(String(modelData.id)) }
            Accessible.name: modelData.title || "Application window";Accessible.role: Accessible.Button;Accessible.onPressAction: picker.selected(String(modelData.id))
        }
        Text { anchors.centerIn: parent;visible: windowList.count===0;width: parent.width;text: picker.query ? "No matching windows" : "No visible application windows";color: Theme.faint;font.pixelSize: Theme.fontSize(11);horizontalAlignment: Text.AlignHCenter;wrapMode: Text.Wrap }
    }
    RowLayout {
        Layout.fillWidth: true
        OrbitButton { text: "Cancel";quiet: true;implicitHeight: 28;onClicked: picker.canceled() }
        Item { Layout.fillWidth: true }
        Text { text: windowList.count+(windowList.count===1 ? " window" : " windows");color: Theme.faint;font.pixelSize: Theme.fontSize(10) }
    }
    Keys.onEscapePressed: picker.canceled()
}
