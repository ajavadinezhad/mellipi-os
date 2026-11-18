import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
SettingsChoice {
    id: picker;objectName:"themePicker"
    model: typeof Orbit.themePresets!=="undefined" ? Orbit.themePresets : []
    property string themeId: Orbit.appearance.themePreset
    property color previewAccent: Theme.accent
    signal themeSelected(string themeId)
    textRole:"name"
    currentIndex: model.findIndex(row=>row.id===picker.themeId)
    readonly property var selectedTheme: currentIndex>=0 && currentIndex<model.length ? model[currentIndex] : null
    displayText: selectedTheme ? selectedTheme.name : "Custom style"
    Accessible.name:"Theme"
    Accessible.description: selectedTheme ? selectedTheme.description : "Choose a theme"
    popupLimit:306;popupObjectName:"themePickerPopup";implicitHeight:Math.max(40,Theme.fontSize(12)+18);implicitWidth:220;leftPadding:10;rightPadding:32
    onActivated:index=>{if(index>=0 && index<model.length)picker.themeSelected(model[index].id);}
    component PaletteSample: Rectangle {
        id:sample
        required property color header
        required property color body
        required property color accent
        Layout.preferredWidth:34
        Layout.preferredHeight:20
        radius:Theme.corner(4)
        border.width:1
        color:body
        Rectangle {x:3;y:3;width:parent.width-6;height:5;radius:1;color:sample.header}
        Rectangle {x:5;y:11;width:10;height:4;radius:1;color:sample.accent}
    }
    contentItem:RowLayout {
        spacing:10
        PaletteSample {
            body:picker.selectedTheme ? picker.selectedTheme.palette.surface : Theme.surface
            border.color:picker.selectedTheme ? (picker.selectedTheme.frame || {}).trim || picker.selectedTheme.palette.border : Theme.frameTrim
            accent:picker.selectedTheme ? picker.selectedTheme.accent : picker.previewAccent
            header:picker.selectedTheme ? (picker.selectedTheme.frame || {}).header || picker.selectedTheme.palette.raised : Theme.headerSurface
        }
        Text {Layout.fillWidth:true;text:picker.displayText;color:Theme.text;font.pixelSize:Theme.fontSize(12);elide:Text.ElideRight}
    }
    delegate:ItemDelegate {
        required property var modelData
        required property int index
        width:picker.optionWidth;implicitHeight:Math.max(38,Theme.fontSize(12)+18)
        highlighted:picker.highlightedIndex===index
        text:modelData.name
        Accessible.name: text
        Accessible.selected: picker.currentIndex===index
        contentItem:RowLayout {
            spacing:10
            PaletteSample {
                body:modelData.palette.surface;border.color:(modelData.frame || {}).trim || modelData.palette.border
                accent:modelData.accent
                header:(modelData.frame || {}).header || modelData.palette.raised
            }
            Text {Layout.fillWidth:true;text:modelData.name;color:Theme.text;font.pixelSize:Theme.fontSize(12);elide:Text.ElideRight}
            ControlMark {Layout.preferredWidth:12;Layout.preferredHeight:12;check:true;opacity:picker.currentIndex===index ? 1 : 0;ink:Theme.accentInk}
        }
        background:Rectangle {radius:Theme.corner(6);color:parent.highlighted ? Theme.hover : picker.currentIndex===index ? Theme.selectedSurface : "transparent"}
    }
}
