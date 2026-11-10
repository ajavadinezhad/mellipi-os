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
        Text {Layout.fillWidth:true;text:"Getting around Abstract";color:Theme.text;font.pixelSize:Theme.fontSize(15);wrapMode:Text.Wrap}
        SettingsGroup {
            title: "Find an app or action"
            Text {Layout.fillWidth:true;text:"Press Super and type an app, window, setting or action. Try sound, display, lock or log out. Super is usually the key with the Windows logo.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            OrbitButton {objectName:"guideOpenSearch";text:"Open search";Layout.fillWidth:true;quiet:true;onClicked:Orbit.showPanel("launcher")}
        }
        SettingsGroup {
            title: "Useful keys"
            Repeater {
                model: [
                    {keys:"Super",task:"Find apps, windows and actions"},
                    {keys:"Alt + Tab",task:"Switch open windows"},
                    {keys:"Ctrl + Alt + ↑ / ↓",task:"Previous / next workspace"},
                    {keys:"Super + 1–4",task:"Go to a workspace"},
                    {keys:"Super + F11 / F12",task:"Default volume down / up"},
                    {keys:"Super + F10",task:"Default mute / unmute"},
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
            Text {Layout.fillWidth:true;text:"Open Super → Saved layouts to save app positions and workspaces. Layouts reuse open windows; they do not save documents or browser tabs. Undo restores Abstract arrangement changes.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
        }
        SettingsGroup {
            title: "Daily controls"
            Text {Layout.fillWidth:true;text:"Quick settings has volume, brightness and connections. Its Power tab has lock, switch user, log out and shutdown. Right-click an app for window actions; Menu or Shift+F10 also opens its menu.";wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:Theme.fontSize(11)}
            OrbitButton {objectName:"guideOpenControls";text:"Open quick controls";Layout.fillWidth:true;quiet:true;onClicked:Orbit.showPanel("quick")}
        }
    }
}
