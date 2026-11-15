import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ScrollView {
    id: guide;objectName: "gettingAroundPanel"
    signal sectionRequested(int section)
    clip: true;contentWidth: availableWidth;implicitHeight: 440
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ColumnLayout {
        width: guide.availableWidth;spacing: 12
        Text {Layout.fillWidth:true;text:"Getting around Mellipi";color:Theme.text;font.pixelSize:Theme.fontSize(15);wrapMode:Text.Wrap}
        SettingsGroup {
            title: "Find an app or action"
            Text {Layout.fillWidth:true;text:"Press Super (usually the Windows key), then type what you need: an app, window, setting, or action.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            OrbitButton {objectName:"guideOpenSearch";text:"Open search";Layout.fillWidth:true;quiet:true;onClicked:Orbit.showPanel("launcher")}
        }
        SettingsGroup {
            title: "Default shortcuts"
            Repeater {
                model: [
                    {keys:"Alt + Tab",task:"Switch open windows"},
                    {keys:"Ctrl + Alt + ↑ / ↓",task:"Previous / next workspace"},
                    {keys:"Super + 1–4",task:"Go to a workspace"},
                    {keys:"Super + F11 / F12",task:"Volume down / up"},
                    {keys:"Super + F10",task:"Mute / unmute"},
                    {keys:"Esc",task:"Close the current panel"}
                ]
                delegate: ColumnLayout {
                    required property var modelData
                    Layout.fillWidth:true;spacing:2;Layout.topMargin:4;Layout.bottomMargin:4
                    Text {Layout.fillWidth:true;text:modelData.keys;color:Theme.text;font.pixelSize:Theme.fontSize(11);wrapMode:Text.Wrap}
                    Text {Layout.fillWidth:true;text:modelData.task;color:Theme.muted;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap}
                }
            }
            OrbitButton {objectName:"guideOpenShortcuts";text:"Customize shortcuts";Layout.fillWidth:true;quiet:true;onClicked:guide.sectionRequested(3)}
        }
        SettingsGroup {
            title: "Arrange your work"
            Text {Layout.fillWidth:true;text:"Use Super → Saved layouts to reopen apps and restore their window positions. Apps handle their own documents and tabs.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }
        SettingsGroup {
            title: "Daily controls"
            Text {Layout.fillWidth:true;text:"Use Quick Settings for volume, brightness, and connections. Find logout and other session actions under Power. Right-click an app, or press Menu or Shift+F10, for window actions.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            OrbitButton {objectName:"guideOpenControls";text:"Open quick controls";Layout.fillWidth:true;quiet:true;onClicked:Orbit.showPanel("quick")}
        }
    }
}
