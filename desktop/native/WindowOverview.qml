import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: overview
    property var windows: []
    readonly property var filteredWindows: {
        var query=search.text.trim().toLowerCase();
        return windows.filter(function(window) {
            return !query || String(window.title || "").toLowerCase().indexOf(query)>=0 || String(window.klass || "").toLowerCase().indexOf(query)>=0;
        });
    }
    spacing: 10
    function activate(index) {
        if(index>=0 && index<filteredWindows.length) Orbit.focusWindow(filteredWindows[index].id);
    }
    RowLayout {
        Layout.fillWidth: true;spacing: 8
        OrbitField {
            id: search;objectName: "overviewSearch";Layout.fillWidth: true;Layout.minimumWidth: 120
            implicitHeight: 36;font.pixelSize: Theme.fontSize(12);leftPadding: 12;rightPadding: 12
            placeholderText: "Search windows"
            onTextChanged: windowGrid.currentIndex=0
            onAccepted: overview.activate(windowGrid.currentIndex)
            Keys.onDownPressed: {windowGrid.forceActiveFocus();windowGrid.currentIndex=Math.max(0,windowGrid.currentIndex);}
            Keys.onEscapePressed: event => {if(text.length){text="";event.accepted=true;}else event.accepted=false;}
        }
        OrbitButton {
            text: "Show desktop";quiet: true;implicitHeight: 36;font.pixelSize: Theme.fontSize(11)
            onClicked: Orbit.showDesktop()
        }
    }
    Flow {
        id: workspaceFlow;Layout.fillWidth: true;Layout.preferredHeight: childrenRect.height;spacing: 4
        Repeater {
            model: Orbit.desktops
            OrbitButton {
                required property var modelData
                text: modelData.name || ("Space "+(modelData.id+1));quiet: true
                implicitHeight: 28;font.pixelSize: Theme.fontSize(11);padding: 6
                onClicked: Orbit.switchDesktop(modelData.id)
                background: Rectangle {
                    radius: Theme.corner(6);color: parent.hovered ? Theme.hover : modelData.active ? Theme.raised : "transparent"
                    border.color: modelData.active ? Theme.accent : "transparent"
                }
            }
        }
    }
    Text {
        text: search.text.trim().length ? overview.filteredWindows.length+" of "+overview.windows.length+" windows" : overview.windows.length+" windows"
        color: Theme.muted;font.pixelSize: Theme.fontSize(11);Layout.fillWidth: true
    }
    GridView {
        id: windowGrid;objectName: "overviewGrid";Layout.fillWidth: true;Layout.fillHeight: true;Layout.rightMargin: -8
        readonly property int columns: width-8>=620 ? 3 : width-8>=340 ? 2 : 1
        cellWidth: width/columns;cellHeight: 104;clip: true
        model: overview.filteredWindows;currentIndex: 0;keyNavigationEnabled: true;activeFocusOnTab: true
        highlightMoveDuration: 0;boundsBehavior: Flickable.StopAtBounds
        Keys.onReturnPressed: overview.activate(currentIndex)
        Keys.onEnterPressed: overview.activate(currentIndex)
        onCurrentIndexChanged: if(currentIndex>=0)positionViewAtIndex(currentIndex,GridView.Contain)
        delegate: Item {
            required property var modelData;required property int index
            width: windowGrid.cellWidth;height: windowGrid.cellHeight
            Rectangle {
                id: card;width: parent.width-8;height: 96;radius: Theme.corner(8)
                color: windowHit.containsMouse || (windowGrid.activeFocus && windowGrid.currentIndex===index) ? Theme.hover : Theme.surface
                border.color: windowGrid.activeFocus && windowGrid.currentIndex===index ? Theme.accent : Theme.border
                Rectangle { visible: !!modelData.active;x: 0;y: 12;width: 2;height: parent.height-24;radius: 1;color: Theme.accent }
                Image {
                    x: 12;y: 14;width: 28;height: 28;source: "image://icons/"+(modelData.icon || "application-x-executable")
                    sourceSize: Qt.size(32,32);fillMode: Image.PreserveAspectFit
                }
                Text {
                    x: 50;y: 13;width: Math.max(20,parent.width-84);height: 36
                    text: modelData.title || "Untitled window";textFormat: Text.PlainText
                    color: Theme.text;font.pixelSize: Theme.fontSize(12);wrapMode: Text.Wrap;maximumLineCount: 2;elide: Text.ElideRight
                }
                Text {
                    x: 50;y: 62;width: parent.width-62
                    text: modelData.desktop<0 ? "All spaces" : "Space "+(modelData.desktop+1)
                    textFormat: Text.PlainText;color: Theme.muted;font.pixelSize: Theme.fontSize(10);elide: Text.ElideRight
                }
                MouseArea {
                    id: windowHit;anchors.fill: parent;hoverEnabled: true;acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: mouse => {
                        windowGrid.currentIndex=index;
                        if(mouse.button===Qt.RightButton){Orbit.openPanelContext(windowHit,"window",modelData.id,mouse.x,mouse.y);}
                        else overview.activate(index);
                    }
                }
                OrbitButton {
                    x: parent.width-width-5;y: 5;implicitWidth: 24;implicitHeight: 24;padding: 0
                    text: "×";quiet: true;font.pixelSize: Theme.fontSize(15);hint: "Close window";onClicked: Orbit.closeWindow(modelData.id)
                    Accessible.name: "Close "+(modelData.title || "window")
                }
                Accessible.name: modelData.title || "Window";Accessible.role: Accessible.Button
                Accessible.onPressAction: overview.activate(index)
            }
        }
        Item {
            anchors.centerIn: parent;width: Math.min(parent.width,320);height: emptyContent.implicitHeight
            visible: windowGrid.count===0
            ColumnLayout {
                id: emptyContent;anchors.left: parent.left;anchors.right: parent.right;spacing: 10
                Text {
                    text: overview.windows.length ? "No matching windows" : "No open windows"
                    color: Theme.text;font.pixelSize: Theme.fontSize(13);Layout.fillWidth: true;horizontalAlignment: Text.AlignHCenter
                }
                OrbitButton {
                    Layout.alignment: Qt.AlignHCenter;text: overview.windows.length ? "Clear search" : "Open apps";quiet: true
                    onClicked: {if(overview.windows.length)search.text="";else Orbit.showPanel("launcher");}
                }
            }
        }
    }
    Component.onCompleted: search.forceActiveFocus()
}
