import QtQuick 2.15
import QtQuick.Controls 2.15
import "."
ComboBox {
    id:choice
    property int popupLimit: 240
    property string popupObjectName: ""
    textRole:"name";font.pixelSize:Theme.fontSize(12);implicitHeight:Math.max(34,font.pixelSize+14);implicitWidth:180;leftPadding:10;rightPadding:28
    contentItem:Text {text:choice.displayText;color:choice.enabled ? Theme.text : Theme.disabled;font:choice.font;verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight;textFormat:Text.PlainText}
    indicator:Text {x:choice.width-width-10;y:(choice.height-height)/2;text:"⌄";color:Theme.muted;font.pixelSize:16}
    background:Rectangle {color:choice.down ? Theme.hover : Theme.raised;radius:Theme.corner(8);border.color:choice.activeFocus ? Theme.focusColor : choice.enabled ? Theme.controlBorder : Theme.border;border.width:choice.activeFocus && Theme.highContrast ? 2 : 1}
    delegate:ItemDelegate {
        id:option
        required property var modelData
        required property int index
        width:choice.width-2;implicitHeight:Math.max(34,choice.font.pixelSize+14);highlighted:choice.highlightedIndex===index
        text:typeof modelData==="string" ? modelData : modelData[choice.textRole]
        Accessible.name: option.text
        contentItem:Item {
            implicitHeight: label.implicitHeight
            Text {id:label;anchors.left:parent.left;anchors.right:check.left;anchors.verticalCenter:parent.verticalCenter;text:option.text;color:Theme.text;font:choice.font;elide:Text.ElideRight;textFormat:Text.PlainText}
            Text {id:check;anchors.right:parent.right;anchors.verticalCenter:parent.verticalCenter;text:index===choice.currentIndex ? "✓" : "";color:Theme.accentInk}
        }
        background:Rectangle {color:parent.highlighted ? Theme.hover : index===choice.currentIndex ? Theme.selectedSurface : Theme.raised}
    }
    popup:Popup {
        objectName:choice.popupObjectName;y:choice.height+2;width:choice.width;padding:1;implicitHeight:Math.min(choice.popupLimit,choices.contentHeight+2)
        contentItem:ListView {id:choices;clip:true;implicitHeight:contentHeight;model:choice.popup.visible ? choice.delegateModel : null;currentIndex:choice.highlightedIndex;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}}
        background:Rectangle {color:Theme.raised;border.color:Theme.controlBorder;border.width:1;radius:Theme.corner(8)}
    }
}
