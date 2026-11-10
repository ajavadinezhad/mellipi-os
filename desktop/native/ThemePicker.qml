import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ComboBox {
    id: picker;objectName:"themePicker"
    model: typeof Orbit.themePresets!=="undefined" ? Orbit.themePresets : []
    textRole:"name"
    currentIndex: model.findIndex(row=>row.id===Orbit.appearance.themePreset)
    readonly property var selectedTheme: currentIndex>=0 && currentIndex<model.length ? model[currentIndex] : null
    displayText: selectedTheme ? selectedTheme.name : "Custom style"
    Accessible.name:"Theme"
    Accessible.description: selectedTheme ? selectedTheme.description : "Choose a theme"
    implicitHeight:40;implicitWidth:220;leftPadding:10;rightPadding:32
    onActivated:index=>{if(index>=0 && index<model.length)Orbit.applyTheme(model[index].id);}
    contentItem:RowLayout {
        spacing:10
        Rectangle {Layout.preferredWidth:22;Layout.preferredHeight:22;radius:Theme.corner(3);color:picker.selectedTheme ? picker.selectedTheme.background : Theme.background;border.color:picker.selectedTheme ? picker.selectedTheme.palette.border : Theme.border
            Rectangle {x:5;y:8;width:12;height:5;radius:1;color:picker.selectedTheme ? picker.selectedTheme.accent : Theme.accent}
        }
        Text {Layout.fillWidth:true;text:picker.displayText;color:Theme.text;font.pixelSize:Theme.fontSize(12);elide:Text.ElideRight}
    }
    indicator:Text {x:picker.width-width-12;y:(picker.height-height)/2;text:"⌄";color:Theme.muted;font.pixelSize:16}
    background:Rectangle {color:picker.down ? Theme.hover : Theme.surface;radius:Theme.corner(8);border.width:picker.activeFocus && Theme.highContrast ? 2 : 1;border.color:picker.activeFocus ? Theme.focusColor : Theme.border}
    delegate:ItemDelegate {
        required property var modelData
        required property int index
        width:picker.width-2;implicitHeight:38
        highlighted:picker.highlightedIndex===index
        text:modelData.name
        contentItem:RowLayout {
            spacing:10
            Rectangle {Layout.preferredWidth:18;Layout.preferredHeight:18;radius:Theme.corner(3);color:modelData.background;border.color:modelData.palette.border
                Rectangle {anchors.centerIn:parent;width:10;height:4;color:modelData.accent}
            }
            Text {Layout.fillWidth:true;text:modelData.name;color:Theme.text;font.pixelSize:Theme.fontSize(12);elide:Text.ElideRight}
            Text {text:Orbit.appearance.themePreset===modelData.id ? "✓" : "";color:Theme.accent;font.pixelSize:12}
        }
        background:Rectangle {color:parent.highlighted ? Theme.hover : Theme.raised}
    }
    popup:Popup {
        objectName:"themePickerPopup"
        y:picker.height+2;width:picker.width;padding:1
        implicitHeight:Math.min(306,themeList.contentHeight+2)
        contentItem:ListView {
            id:themeList;clip:true;implicitHeight:contentHeight
            model:picker.popup.visible ? picker.delegateModel : null
            currentIndex:picker.highlightedIndex;boundsBehavior:Flickable.StopAtBounds
            ScrollBar.vertical:ScrollBar {}
        }
        background:Rectangle {color:Theme.raised;border.color:Theme.border;radius:Theme.corner(8)}
    }
}
