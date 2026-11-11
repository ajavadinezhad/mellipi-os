import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
ColumnLayout {
    id: panel;objectName: "intelligencePanel"
    property bool wide: width>=650
    spacing: 10
    RowLayout {
        Layout.fillWidth: true
        Text { text: Orbit.model ? Orbit.model : "No model configured";color: Theme.muted;font.pixelSize: Theme.fontSize(11);Layout.fillWidth: true;elide: Text.ElideRight;textFormat: Text.PlainText }
        Text { text: Orbit.busy ? "Responding…" : Orbit.model ? "Ready" : "Unavailable";color: Theme.faint;font.pixelSize: Theme.fontSize(10) }
        OrbitButton { visible: !panel.wide;text: "Context · "+Orbit.selected.length;quiet: true;implicitHeight: 26;onClicked: Orbit.showPanel("shelf") }
    }
    ListView {
        visible: !panel.wide && Orbit.selectedObjects.length>0
        Layout.fillWidth: true;Layout.preferredHeight: 26;orientation: ListView.Horizontal;clip: true;spacing: 4;reuseItems: true
        model: Orbit.selectedObjects
        delegate: OrbitButton { required property var modelData;text: (modelData.title || "Untitled").slice(0,20)+" ×";quiet: true;implicitHeight: 24;hint: "Detach context";onClicked: Orbit.attach(modelData.id) }
    }
    RowLayout {
        Layout.fillWidth: true;Layout.fillHeight: true;spacing: 10
        ColumnLayout {
            Layout.fillWidth: true;Layout.fillHeight: true;spacing: 8
            Rectangle {
                Layout.fillWidth: true;Layout.fillHeight: true;Layout.minimumHeight: 100
                color: Theme.surface;radius: Theme.corner(11);border.color: Theme.border
                ScrollView {
                    id: answerScroll;anchors.fill: parent;anchors.margins: 10;clip: true;contentWidth: availableWidth
                    TextArea {
                        id: answerText;objectName: "aiAnswer";width: answerScroll.availableWidth;implicitWidth: 200;padding: 2
                        text: Orbit.answer || (Orbit.busy ? "Thinking with your attached context…" : Orbit.model ? "Ask a question or attach context to begin." : "No AI model is configured.")
                        readOnly: true;selectByMouse: true;wrapMode: TextEdit.Wrap;textFormat: TextEdit.PlainText
                        color: Orbit.answer ? Theme.text : Theme.faint;font.pixelSize: Theme.fontSize(13);background: Item {}
                    }
                }
            }
            TextArea {
                id: prompt;objectName: "aiPrompt";Layout.fillWidth: true;Layout.preferredHeight: 72
                placeholderText: "Ask a question…";color: Theme.text;placeholderTextColor: Theme.muted
                wrapMode: TextEdit.Wrap;selectByMouse: true;padding: 10;font.pixelSize: Theme.fontSize(12)
                background: Rectangle { color: Theme.surface;radius: Theme.corner(9);border.color: prompt.activeFocus ? Theme.accent : Theme.border }
                Keys.onPressed: event => {
                    if((event.key===Qt.Key_Return || event.key===Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
                        if(!Orbit.busy && Orbit.model && prompt.text.trim())Orbit.ask(prompt.text);
                        event.accepted=true;
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true;spacing: 5
                OrbitButton { text: "Copy answer";quiet: true;implicitHeight: 28;enabled: !Orbit.busy && Orbit.answer.length>0;onClicked: {answerText.selectAll();answerText.copy();answerText.deselect();} }
                OrbitButton { objectName: "aiSaveAction";text: "Save";quiet: true;implicitHeight: 28;visible: Orbit.answerReady && !Orbit.busy;onClicked: Orbit.saveAnswer() }
                Item { Layout.fillWidth: true }
                OrbitButton { objectName: "aiAskAction";text: Orbit.busy ? "Cancel" : "Ask ↑";accent: !Orbit.busy;implicitHeight: 30;enabled: Orbit.busy || (Orbit.model!=="" && prompt.text.trim()!=="");onClicked: Orbit.busy ? Orbit.cancelAI() : Orbit.ask(prompt.text) }
            }
        }
        Rectangle {
            visible: panel.wide;Layout.preferredWidth: 190;Layout.fillHeight: true
            color: Theme.surface;radius: Theme.corner(11);border.color: Theme.border
            ColumnLayout {
                anchors.fill: parent;anchors.margins: 10;spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Context";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true }
                    Text { text: Orbit.selected.length;color: Theme.faint;font.pixelSize: Theme.fontSize(10) }
                }
                ListView {
                    id: contextList;Layout.fillWidth: true;Layout.fillHeight: true;clip: true;spacing: 4;reuseItems: true
                    model: Orbit.selectedObjects
                    delegate: Rectangle {
                        required property var modelData;width: contextList.width;height: 48;radius: Theme.corner(6);color: Theme.raised
                        Text { x: 8;y: 8;width: parent.width-38;text: modelData.title || "Untitled";color: Theme.text;font.pixelSize: Theme.fontSize(11);elide: Text.ElideRight;textFormat: Text.PlainText }
                        Text { x: 8;y: 26;width: parent.width-38;text: modelData.kind=== "file" ? "File" : modelData.kind==="result" ? "Answer" : "Note";color: Theme.faint;font.pixelSize: Theme.fontSize(10) }
                        IconButton { anchors.right: parent.right;anchors.rightMargin: 2;anchors.verticalCenter: parent.verticalCenter;iconName: "close";implicitWidth: 26;implicitHeight: 26;hint: "Detach context";onClicked: Orbit.attach(modelData.id) }
                    }
                    Text { anchors.centerIn: parent;width: parent.width;text: "No attached items";visible: contextList.count===0;color: Theme.faint;font.pixelSize: Theme.fontSize(11);horizontalAlignment: Text.AlignHCenter;wrapMode: Text.Wrap }
                }
                OrbitButton { text: "+ Add context";Layout.fillWidth: true;implicitHeight: 28;onClicked: Orbit.showPanel("shelf") }
                Text { text: "Only attached items are sent with your question.";color: Theme.faint;font.pixelSize: Theme.fontSize(10);Layout.fillWidth: true;wrapMode: Text.Wrap }
            }
        }
    }
}
