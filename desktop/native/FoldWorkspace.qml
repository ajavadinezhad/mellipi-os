import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

Item {
    id: fold
    objectName: "foldWorkspace"
    implicitWidth: 728;implicitHeight: 490
    readonly property bool narrow: width<560
    readonly property string view: Fold.state.view || "work"
    readonly property var currentSpace: Orbit.desktops.find(space => space.active) || ({name:"Workspace",id:0})
    readonly property string workspaceName: /^\d+$/.test(String(currentSpace.name || "")) ? "Workspace "+currentSpace.name : currentSpace.name || "Workspace "+(currentSpace.id+1)
    readonly property var windows: Orbit.windows
    readonly property string windowCount: windows.length+(windows.length===1 ? " window" : " windows")
    Component.onCompleted: Fold.setView("apps")
    onViewChanged: if(view!=="work")Qt.callLater(function(){unified.focusSearch();})
    ColumnLayout {
        anchors.fill: parent;spacing: Theme.compact ? 10 : 12
        SheetHeader {
            Layout.fillWidth: true;Layout.preferredHeight: implicitHeight
            section: "Mellipi / "+fold.workspaceName
            title: fold.view==="work" ? "Files & notes" : "Apps & windows"
            subtitle: ""
            onCloseRequested: Orbit.dismiss()
        }
        RowLayout {
            visible: fold.view==="work";Layout.fillWidth: true
            OrbitButton {objectName: "foldBackButton";text: "← Apps & windows";quiet: true;onClicked: Fold.setView("apps")}
            Item {Layout.fillWidth: true}
        }
        RowLayout {
            Layout.fillWidth: true;Layout.fillHeight: true;spacing: 14
        StackLayout {
            id: foldPages
            property bool ready: false
            Layout.fillWidth: true;Layout.fillHeight: true
            currentIndex: fold.view==="work" ? 0 : 1
            transform: Translate {id: foldPageShift}
            Component.onCompleted: ready=true
            onCurrentIndexChanged: {
                if(!ready)return;
                foldViewEnter.stop();
                if(Theme.reducedMotion){opacity=1;foldPageShift.y=0;}
                else foldViewEnter.restart();
            }
            ParallelAnimation {
                id: foldViewEnter
                NumberAnimation {target: foldPages;property: "opacity";from: .72;to: 1;duration: Theme.motion;easing.type: Easing.OutCubic}
                NumberAnimation {target: foldPageShift;property: "y";from: 5;to: 0;duration: Theme.motion;easing.type: Easing.OutCubic}
            }
            Rectangle {
                id: notesLeaf;objectName: "foldNotesLeaf"
                Layout.fillHeight: true;Layout.fillWidth: true
                color: Theme.surface;radius: Theme.corner(6);border.width: Theme.surfaceOutline;border.color: Theme.border
                ColumnLayout {
                    anchors.fill: parent;anchors.margins: 12;spacing: 8
                    RowLayout {Layout.fillWidth: true;Layout.preferredHeight: 26
                        Text {text: "Notes";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true}
                        IconButton {
                            iconName: "folder";hint: "Open Mellipi Files"
                            onClicked: Orbit.launch("mellipi-files.desktop")
                        }
                    }
                    Rectangle {Layout.fillWidth: true;implicitHeight: 1;color: Theme.border}
                    ScrollView {
                        id: noteScroll;Layout.fillWidth: true;Layout.fillHeight: true;clip: true;contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        TextArea {
                            id: noteEditor;objectName: "foldNoteEditor"
                            width: noteScroll.availableWidth
                            text: Fold.state.noteText || "";placeholderText: "Keep a thought here."
                            wrapMode: TextEdit.Wrap;textFormat: TextEdit.PlainText;color: Theme.text;placeholderTextColor: Theme.faint;font.pixelSize: Theme.fontSize(12);selectByMouse: true
                            padding: 3;background: Item {}
                            onTextChanged: if(text!==Fold.state.noteText)Fold.setNoteText(text)
                        }
                    }
                }
            }
            UnifiedLauncher {id: unified;Layout.fillWidth: true;Layout.fillHeight: true;onToolsRequested: Fold.setView("work")}
        }
        }
        Text {visible: !!Fold.state.error;Layout.fillWidth: true;Layout.maximumHeight: 30;text: Fold.state.error || "";color: Theme.muted;font.pixelSize: Theme.fontSize(10);wrapMode: Text.Wrap;maximumLineCount: 2;elide: Text.ElideRight;textFormat: Text.PlainText}
        RowLayout {
            Layout.fillWidth: true;Layout.preferredHeight: 26;spacing: 7
            Rectangle {width: 5;height: 5;rotation: 45;color: Theme.accent}
            Text {text: fold.windowCount;color: Theme.muted;font.pixelSize: Theme.fontSize(10);Layout.rightMargin: 4}
            Item {Layout.fillWidth: true}
            Text {text: fold.view==="work" ? "Saved locally" : "Enter to open · Right-click for actions";color: Theme.faint;font.pixelSize: Theme.fontSize(10);elide: Text.ElideRight;Layout.maximumWidth: fold.narrow ? 120 : 200}
        }
    }
}
