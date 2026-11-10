import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: panel;objectName: "sessionExitPanel";spacing: 12
    readonly property string actionName: SessionExit.state.action==="reboot" ? "restart" : SessionExit.state.action==="shutdown" ? "shut down" : "log out"
    readonly property string actionLabel: actionName.charAt(0).toUpperCase()+actionName.slice(1)
    readonly property bool hasWindows: SessionExit.windows.length>0
    RowLayout {
        Layout.fillWidth: true;spacing: 12
        Rectangle {
            Layout.preferredWidth: 40;Layout.preferredHeight: 40
            radius: Theme.corner(10);color: Theme.raised
            Canvas {
                id: actionGlyph;anchors.centerIn: parent;width: 22;height: 22
                onPaint: {
                    var c=getContext("2d");c.clearRect(0,0,width,height);
                    c.strokeStyle=Theme.accent;c.lineWidth=1.6;c.lineCap="round";c.lineJoin="round";c.beginPath();
                    if(SessionExit.state.action==="shutdown") {
                        c.arc(11,12,7,-Math.PI*.3,Math.PI*1.3);c.moveTo(11,2);c.lineTo(11,10);
                    } else if(SessionExit.state.action==="reboot") {
                        c.arc(11,11,7,-Math.PI*.3,Math.PI*1.3);
                        c.moveTo(17,2);c.lineTo(17,8);c.lineTo(11,8);
                    } else {
                        c.moveTo(8,3);c.lineTo(3,3);c.lineTo(3,19);c.lineTo(8,19);
                        c.moveTo(9,11);c.lineTo(20,11);c.moveTo(15,6);c.lineTo(20,11);c.lineTo(15,16);
                    }
                    c.stroke();
                }
                Connections {target: SessionExit;function onChanged(){actionGlyph.requestPaint();}}
                Connections {target: Orbit;function onSettingsChanged(){actionGlyph.requestPaint();}}
            }
        }
        ColumnLayout {
            Layout.fillWidth: true;spacing: 4
            Text {Layout.fillWidth: true;text: panel.actionLabel+"?";color: Theme.text;font.pixelSize: Theme.fontSize(18);wrapMode: Text.Wrap}
            Text {
                Layout.fillWidth: true;text: SessionExit.state.armed ? "Save or cancel in each app to continue." : panel.hasWindows ? "Review your apps before leaving." : "No application windows are open."
                color: Theme.muted;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap
            }
        }
    }
    Text {
        visible: panel.hasWindows;Layout.fillWidth: true
        text: SessionExit.windows.length+" open "+(SessionExit.windows.length===1 ? "window" : "windows")
        color: Theme.muted;font.pixelSize: Theme.fontSize(10)
    }
    ListView {
        id: openWindows;objectName: "sessionExitWindows";Layout.fillWidth: true
        visible: panel.hasWindows;Layout.minimumHeight: 0;Layout.fillHeight: true;Layout.maximumHeight: Layout.preferredHeight;Layout.preferredHeight: Math.min(260,contentHeight)
        model: SessionExit.windows;clip: true;spacing: 4;cacheBuffer: 0
        delegate: Rectangle {
            required property var modelData
            width: openWindows.width;height: 58;color: Theme.surface;radius: Theme.corner(4)
            RowLayout {
                anchors.fill: parent;anchors.margins: 8
                ColumnLayout {
                    Layout.fillWidth: true;Layout.minimumWidth: 0
                    Text {Layout.fillWidth: true;text: modelData.title;textFormat: Text.PlainText;elide: Text.ElideRight;color: Theme.text;font.pixelSize: Theme.fontSize(12)}
                    Text {Layout.fillWidth: true;text: modelData.closeRequested ? "Waiting for this app to close" : modelData.minimized ? "Minimized" : modelData.app;textFormat: Text.PlainText;elide: Text.ElideRight;color: Theme.muted;font.pixelSize: Theme.fontSize(10)}
                }
                OrbitButton {text: "Open";implicitHeight: 28;hint: "Return to this application";onClicked: SessionExit.focusWindow(modelData.id)}
            }
        }
    }
    ListView {
        id: protections;visible: count>0;Layout.fillWidth: true;Layout.minimumHeight: 0;Layout.fillHeight: true;Layout.maximumHeight: Layout.preferredHeight;Layout.preferredHeight: Math.min(100,contentHeight)
        model: SessionExit.inhibitors;clip: true;cacheBuffer: 0;spacing: 4
        delegate: Text {required property var modelData;width: protections.width;text: modelData.who+": "+modelData.reason;textFormat: Text.PlainText;color: Theme.text;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap}
    }
    Text {Layout.fillWidth: true;visible: SessionExit.inhibitors.length>0;text: SessionExit.inhibitors.some(r=>r.mode!=="delay") ? "A system operation is still running. Check again when it finishes." : "These apps need time to prepare. Abstract will wait for their windows to close.";color: Theme.muted;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap}
    Text {Layout.fillWidth: true;visible: !!SessionExit.state.error;text: SessionExit.state.error;textFormat: Text.PlainText;color: Theme.text;font.pixelSize: Theme.fontSize(11);wrapMode: Text.Wrap}
    Text {Layout.fillWidth: true;visible: SessionExit.state.checking;text: SessionExit.state.action==="logout" ? "Preparing to log out…" : "Checking system protections…";color: Theme.muted;font.pixelSize: Theme.fontSize(11)}
    Text {
        Layout.fillWidth: true
        text: SessionExit.state.armed ? "New windows stay open. Return to work to cancel." : panel.hasWindows ? "Apps may ask you to save. Background tasks also end when you leave." : "Background tasks also end when you leave."
        color: Theme.faint;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap
    }
    RowLayout {
        Layout.fillWidth: true;spacing: 8
        OrbitButton {objectName: "sessionExitCancel";text: "Return to work";Layout.fillWidth: true;onClicked: {SessionExit.cancel();Orbit.dismiss();}}
        OrbitButton {objectName: "sessionExitCheck";text: "Check again";visible: !!SessionExit.state.error || SessionExit.inhibitors.length>0;enabled: !SessionExit.state.checking;onClicked: SessionExit.recheck()}
    }
    OrbitButton {objectName: "sessionExitConfirm";text: SessionExit.state.armed ? "Waiting for apps to close…" : panel.hasWindows ? "Close apps and "+panel.actionName : panel.actionLabel;Layout.fillWidth: true;accent: true;enabled: !SessionExit.state.armed && !SessionExit.state.checking;onClicked: SessionExit.closeAndWait()}
}
