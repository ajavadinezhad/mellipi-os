import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: view;objectName: "accessibilityPanel"
    readonly property var keyboardTool: DesktopTools.tools["keyboard"] || ({available:false,reason:"No compatible on-screen keyboard is installed."})
    clip: true;contentWidth: availableWidth;implicitHeight: content.implicitHeight
    function reveal(item) {
        var flick=contentItem;
        if(!flick || !item)return;
        var y=item.mapToItem(content,0,0).y;
        if(y<flick.contentY)flick.contentY=y;
        else if(y+item.height>flick.contentY+flick.height)flick.contentY=y+item.height-flick.height;
    }
    ColumnLayout {
        id: content;width: view.availableWidth;spacing: 10
        SettingsGroup {
            title: "Reading"
            OrbitButton {
                text:"Desktop text size…";quiet:true;Layout.fillWidth:true
                onClicked:Orbit.activateSystemAction("text-size")
            }
            Text {Layout.fillWidth: true;Layout.margins: 6;text: "High contrast is under Appearance.";wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
        }
        SettingsGroup {
            title: "Keyboard and motion"
            OrbitButton {
                text:"Motion settings…";quiet:true;Layout.fillWidth:true
                onClicked:Orbit.activateSystemAction("desktop-animations")
            }
            Text {Layout.fillWidth: true;Layout.margins: 6;text: "Use Tab to move between controls. Apps, Unfold and notifications support arrow keys and Enter or Space to activate the selected item.";wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
        }
        SettingsGroup {
            title:"Assistive tools"
            OrbitButton {onActiveFocusChanged: if(activeFocus)view.reveal(this);text:"Open screen reader";Layout.fillWidth:true;enabled:DesktopTools.tools["screen-reader"].available;onClicked:DesktopTools.open("screen-reader")}
            OrbitButton {onActiveFocusChanged: if(activeFocus)view.reveal(this);objectName:"accessibilityKeyboard";text:"On-screen keyboard";Layout.fillWidth:true;enabled:view.keyboardTool.available;hint:view.keyboardTool.reason || "Type in applications using the on-screen keyboard";onClicked:DesktopTools.open("keyboard")}
            Text {visible:!view.keyboardTool.available;Layout.fillWidth:true;Layout.margins:6;text:view.keyboardTool.reason || "Install wvkbd to enable the Wayland keyboard.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(10)}
            OrbitButton {onActiveFocusChanged: if(activeFocus)view.reveal(this);text:"Input method setup";Layout.fillWidth:true;enabled:DesktopTools.tools["input-method"].available;onClicked:DesktopTools.open("input-method")}
            Text {Layout.fillWidth:true;Layout.margins:6;text:"Screen readers use the standard accessibility service. Configure an installed Fcitx or IBus engine for additional languages. The on-screen keyboard types in applications; secure-lock input is handled separately.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }

    }
}
