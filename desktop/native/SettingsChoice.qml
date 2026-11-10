import QtQuick 2.15
import QtQuick.Controls 2.15
import "."
ComboBox {
    id:choice;textRole:"name";implicitHeight:34;implicitWidth:180;leftPadding:10;rightPadding:28
    contentItem:Text {text:choice.displayText;color:choice.enabled ? Theme.text : Theme.disabled;font.pixelSize:Theme.fontSize(12);verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight;textFormat:Text.PlainText}
    indicator:Text {x:choice.width-width-10;y:(choice.height-height)/2;text:"⌄";color:Theme.muted;font.pixelSize:16}
    background:Rectangle {color:choice.down ? Theme.hover : Theme.surface;radius:Theme.corner(8);border.color:choice.activeFocus ? Theme.focusColor : Theme.border;border.width:choice.activeFocus && Theme.highContrast ? 2 : 1}
    delegate:ItemDelegate {
        required property var modelData
        required property int index
        width:choice.width-2;implicitHeight:34;highlighted:choice.highlightedIndex===index
        contentItem:Text {text:typeof modelData==="string" ? modelData : modelData[choice.textRole];color:Theme.text;font.pixelSize:Theme.fontSize(12);elide:Text.ElideRight;textFormat:Text.PlainText}
        background:Rectangle {color:parent.highlighted ? Theme.hover : Theme.raised}
    }
    popup:Popup {
        y:choice.height+2;width:choice.width;padding:1;implicitHeight:Math.min(240,choices.contentHeight+2)
        contentItem:ListView {id:choices;clip:true;implicitHeight:contentHeight;model:choice.popup.visible ? choice.delegateModel : null;currentIndex:choice.highlightedIndex;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}}
        background:Rectangle {color:Theme.raised;border.color:Theme.border;radius:Theme.corner(8)}
    }
}
