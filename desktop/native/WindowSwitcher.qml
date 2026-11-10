import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ListView {
    id: switcher;clip: true;spacing: 6;model: Orbit.switchWindows;currentIndex: Orbit.switchIndex
    highlightMoveDuration: Theme.motion
    onCurrentIndexChanged: positionViewAtIndex(currentIndex,ListView.Contain)
    delegate: Rectangle {
        required property var modelData;required property int index
        width: ListView.view.width;height: 56;radius: Theme.corner(10);color: index===Orbit.switchIndex ? Theme.raised : Theme.surface
        border.color: index===Orbit.switchIndex ? Theme.accent : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.motion } }
        RowLayout {
            anchors.fill: parent;anchors.margins: 10;spacing: 12
            Image { source: "image://icons/"+modelData.icon;Layout.preferredWidth: 32;Layout.preferredHeight: 32;sourceSize: Qt.size(32,32) }
            Text { text: modelData.title;textFormat: Text.PlainText;color: Theme.text;font.pixelSize: Theme.fontSize(13);Layout.fillWidth: true;Layout.minimumWidth: 0;elide: Text.ElideRight }
            Text { text: modelData.desktop<0 ? "All spaces" : "Space "+(modelData.desktop+1);color: Theme.muted;font.pixelSize: Theme.fontSize(10) }
        }
        MouseArea { anchors.fill: parent;onClicked: {Orbit.cycleSwitch(index-Orbit.switchIndex);Orbit.acceptSwitch();} }
    }
}
