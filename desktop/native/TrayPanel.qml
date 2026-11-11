import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    spacing: 8
    ListView {
        id: apps;Layout.fillWidth: true;Layout.fillHeight: true
        clip: true;spacing: 4;model: Tray.items.concat(Background.items.map(o => ({key:o.id,desktopId:o.id,name:o.name,pid:o.pid,iconSource:Theme.iconSource(o.icon),fallback:true})));reuseItems: true
        delegate: Rectangle {
            id: entry;objectName: "trayEntry";required property var modelData
            activeFocusOnTab: true
            Accessible.role: Accessible.Button;Accessible.name: modelData.name
            function activate(){var p=Orbit.itemScreenPoint(entry,entry.width/2,entry.height/2);if(modelData.fallback)Orbit.launch(modelData.desktopId);else{Tray.activate(modelData.key,p.x,p.y);Orbit.dismiss();}}
            Accessible.onPressAction: activate()
            Keys.onReturnPressed: activate()
            Keys.onSpacePressed: activate()
            width: apps.width;height: 44;radius: Theme.corner(8)
            color: hit.containsMouse || activeFocus ? Theme.hover : "transparent";border.color: activeFocus ? Theme.focusColor : "transparent"
            Image { x: 10;anchors.verticalCenter: parent.verticalCenter;width: 22;height: 22;source: modelData.iconSource;fillMode: Image.PreserveAspectFit;sourceSize: Qt.size(32,32);cache: false }
            Column {
                x: 44;anchors.verticalCenter: parent.verticalCenter;width: parent.width-86;spacing: 2
                Text { width: parent.width;text: modelData.name;color: Theme.text;font.pixelSize: Theme.fontSize(12);elide: Text.ElideRight;textFormat: Text.PlainText }
                Text { visible: modelData.fallback === true;text: "Running in background";color: Theme.muted;font.pixelSize: Theme.fontSize(9) }
            }
            MouseArea {
                id: hit;anchors.fill: parent;anchors.rightMargin: 38;hoverEnabled: true;acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: mouse => {var p=Orbit.itemScreenPoint(hit,mouse.x,mouse.y);if(modelData.fallback){if(mouse.button===Qt.RightButton)Orbit.openContext("app",modelData.desktopId,p.x,p.y);else Orbit.launch(modelData.desktopId);}else if(mouse.button===Qt.RightButton)Tray.menu(modelData.key,p.x,p.y);else{Tray.activate(modelData.key,p.x,p.y);Orbit.dismiss();}}
                onWheel: wheel => Tray.scroll(modelData.key,wheel.angleDelta.y)
            }
            IconButton { id: trayActions;anchors.right: parent.right;anchors.verticalCenter: parent.verticalCenter;iconName: "more";implicitWidth: 32;implicitHeight: 30;hint: "App actions";onClicked: {var p=Orbit.itemScreenPoint(trayActions,width,height);if(modelData.fallback)Orbit.openContext("app",modelData.desktopId,p.x,p.y);else Tray.menu(modelData.key,p.x,p.y);} }
        }
        Text { anchors.centerIn: parent;visible: apps.count===0;text: Tray.legacyCount ? "" : "No background apps";color: Theme.muted;font.pixelSize: Theme.fontSize(12) }
    }
    Item {
        id: legacyArea;Layout.fillWidth: true;Layout.preferredHeight: Math.ceil(Tray.legacyCount/8)*30;visible: Tray.legacyCount>0
        function place(){var p=mapToItem(null,0,0);Tray.positionLegacy(Math.round(p.x),Math.round(p.y));}
        onXChanged: place()
        onYChanged: place()
        onHeightChanged: place()
        Component.onCompleted: place()
    }
}
