import QtQuick 2.15
import QtQuick.Controls 2.15
import "."

ComboBox {
    id: choice
    property int popupLimit: 240
    property string popupObjectName: ""
    readonly property int rowHeight: Math.max(Theme.extraCompact ? 30 : 34, font.pixelSize + 14)
    readonly property real optionWidth: Math.max(0, choices.width-(choices.contentHeight>choices.height ? 9 : 0))
    textRole: "name"
    font.pixelSize: Theme.fontSize(12)
    implicitHeight: rowHeight
    implicitWidth: 180
    leftPadding: Theme.compact ? 8 : 11
    rightPadding: 28
    hoverEnabled: true
    contentItem: Text {
        text: choice.displayText;color: choice.enabled ? Theme.text : Theme.disabled
        font: choice.font;verticalAlignment: Text.AlignVCenter;elide: Text.ElideRight;textFormat: Text.PlainText
    }
    indicator: ControlMark {
        x: choice.width - width - 9; y: (choice.height-height)/2
        width: 12;height: 12;up: choice.popup.visible
        ink: choice.enabled ? Theme.muted : Theme.disabled
    }
    background: ControlSurface {
        field: true;controlEnabled: choice.enabled;focused: choice.activeFocus || choice.popup.visible
        hovered: choice.hovered;pressed: choice.down
    }
    delegate: ItemDelegate {
        id: option
        required property var modelData
        required property int index
        readonly property bool selectedOption: index === choice.currentIndex
        width: choice.optionWidth
        implicitHeight: choice.rowHeight
        highlighted: choice.highlightedIndex === index
        text: typeof modelData === "string" ? modelData : modelData[choice.textRole]
        Accessible.name: option.text
        Accessible.selected: selectedOption
        contentItem: Item {
            implicitHeight: label.implicitHeight
            Text {
                id: label
                anchors.left: parent.left;anchors.right: check.left;anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                text: option.text;color: Theme.text;font: choice.font;elide: Text.ElideRight;textFormat: Text.PlainText
            }
            ControlMark {
                id: check
                anchors.right: parent.right;anchors.verticalCenter: parent.verticalCenter
                width: 12;height: 12;check: true;visible: option.selectedOption;ink: Theme.accentInk
            }
        }
        background: Rectangle {
            radius: Theme.corner(6)
            color: option.highlighted ? Theme.hover : option.selectedOption ? Theme.selectedSurface : "transparent"
        }
    }
    popup: Popup {
        objectName: choice.popupObjectName
        y: choice.height + 3
        width: choice.width
        padding: 4
        margins: 6
        implicitHeight: Math.min(choice.popupLimit, choices.contentHeight + topPadding + bottomPadding)
        contentItem: ListView {
            id: choices
            clip: true
            implicitHeight: contentHeight
            model: choice.popup.visible ? choice.delegateModel : null
            currentIndex: choice.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
        }
        background: Rectangle {
            color: Theme.raised;border.color: Theme.highContrast ? Theme.controlBorder : Theme.border
            border.width: 1;radius: Theme.corner(9)
        }
    }
}
