import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
Item {
    id: sectionIndex
    property var sections: []
    property int current: 0
    signal selected(int value)
    implicitWidth: Math.max(144,Math.min(184,Theme.fontSize(11)*8+56))
    implicitHeight: Math.max(320,Math.min(480,sections.length*(Math.max(Theme.extraCompact ? 26 : Theme.compact ? 32 : 38,Theme.fontSize(11)+(Theme.extraCompact ? 12 : 16))+2)+80))
    function revealCurrent() {
        var selectedIndex=sections.findIndex(row => row.value===current);
        entries.currentIndex=selectedIndex;
        if(selectedIndex>=0)entries.positionViewAtIndex(selectedIndex,ListView.Contain);
    }
    onCurrentChanged: Qt.callLater(revealCurrent)
    onSectionsChanged: Qt.callLater(revealCurrent)
    Component.onCompleted: Qt.callLater(revealCurrent)
    Rectangle {anchors.fill: parent;color: Theme.surface;radius: Theme.corner(10)}
    ListView {
        id: entries;objectName: "settingsSectionsList"
        anchors.fill: parent;anchors.margins: 5
        model: sectionIndex.sections;clip: true;spacing: 2;cacheBuffer: 0
        boundsBehavior: Flickable.StopAtBounds;activeFocusOnTab: true;keyNavigationEnabled: true
        section.property: "group";section.criteria: ViewSection.FullString
        section.delegate: Text {
            width: entries.width;height: section ? Math.max(Theme.extraCompact ? 20 : 24,Theme.fontSize(9)+(Theme.extraCompact ? 8 : 12)) : 0
            text: section || "";verticalAlignment: Text.AlignVCenter;color: Theme.faint
            font.pixelSize: Theme.fontSize(9);font.letterSpacing: .6;elide: Text.ElideRight
        }
        ScrollBar.vertical: ScrollBar {policy: entries.contentHeight>entries.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff}
        Keys.onReturnPressed: if(currentIndex>=0)sectionIndex.selected(sectionIndex.sections[currentIndex].value)
        Keys.onEnterPressed: if(currentIndex>=0)sectionIndex.selected(sectionIndex.sections[currentIndex].value)
        Keys.onSpacePressed: if(currentIndex>=0)sectionIndex.selected(sectionIndex.sections[currentIndex].value)
        delegate: OrbitButton {
            id: entry;required property var modelData;required property int index
            objectName: "sectionIndex_"+modelData.value
            width: entries.width;height: Math.max(Theme.extraCompact ? 26 : Theme.compact ? 32 : 38,Theme.fontSize(11)+(Theme.extraCompact ? 12 : 16));padding: 6;quiet: true
            text: modelData.label;hint: modelData.description || modelData.label
            Accessible.name: modelData.label;Accessible.description: modelData.description || ""
            contentItem: RowLayout {
                spacing: 8
                Image {
                    visible: !!entry.modelData.icon
                    Layout.preferredWidth: 16;Layout.preferredHeight: 16
                    sourceSize: Qt.size(16,16)
                    source: visible ? Theme.symbolicIconSource(entry.modelData.icon) : ""
                }
                Text {
                    Layout.fillWidth: true;Layout.minimumWidth: 0
                    text: entry.modelData.label;font.pixelSize: Theme.fontSize(11)
                    color: sectionIndex.current===entry.modelData.value ? Theme.text : Theme.muted
                    elide: Text.ElideRight;verticalAlignment: Text.AlignVCenter
                }
            }
            background: Rectangle {
                color: sectionIndex.current===entry.modelData.value ? Theme.selectedSurface : entry.hovered || entry.activeFocus ? Theme.hover : "transparent"
                radius: Theme.corner(5)
                border.color: Theme.focusColor;border.width: entry.activeFocus ? 1 : 0
                Rectangle {width: 2;height: parent.height;color: Theme.accent;visible: sectionIndex.current===entry.modelData.value}
            }
            onClicked: sectionIndex.selected(modelData.value)
        }
    }
}
