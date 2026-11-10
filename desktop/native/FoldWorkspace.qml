import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

Item {
    id: fold
    objectName: "foldWorkspace"
    implicitWidth: 728;implicitHeight: 490
    readonly property bool narrow: width<560
    property string leaf: "files"
    readonly property string view: Fold.state.view || "work"
    readonly property var selectedItem: Fold.items.find(item => item.id===Fold.state.selectedId) || ({})
    readonly property var currentSpace: Orbit.desktops.find(space => space.active) || ({name:"Workspace",id:0})
    readonly property string workspaceName: /^\d+$/.test(String(currentSpace.name || "")) ? "Workspace "+currentSpace.name : currentSpace.name || "Workspace "+(currentSpace.id+1)
    readonly property var windows: Orbit.windows
    readonly property string windowCount: windows.length+(windows.length===1 ? " window" : " windows")
    function openItem(item) {
        if(item.isDir || item.kind==="folder" || item.kind==="directory")Fold.setFolder(item.source || item.id);
        else {Fold.select(item.id);Orbit.dismiss();Fold.openItem(item.id);}
    }
    Component.onCompleted: Fold.setView("apps")
    onViewChanged: if(view!=="work")Qt.callLater(function(){unified.focusSearch();})
    ColumnLayout {
        anchors.fill: parent;spacing: Theme.compact ? 10 : 12
        SheetHeader {
            Layout.fillWidth: true;Layout.preferredHeight: implicitHeight
            section: "Abstract / "+fold.workspaceName
            title: fold.view==="work" ? "Files & notes" : "Apps & windows"
            subtitle: fold.view==="work" ? "Files and local notes." : "Find an app or return to an open window."
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
            Item {
                ColumnLayout {
                    anchors.fill: parent;spacing: 7
                    RowLayout {
                        visible: fold.narrow;Layout.fillWidth: true;Layout.preferredHeight: visible ? 28 : 0
                        OrbitButton {objectName: "foldFilesTab";text: "Files";quiet: fold.leaf!=="files";implicitHeight: 26;Layout.fillWidth: true;onClicked: fold.leaf="files"}
                        OrbitButton {objectName: "foldNotesTab";text: "Notes";quiet: fold.leaf!=="notes";implicitHeight: 26;Layout.fillWidth: true;onClicked: fold.leaf="notes"}
                    }
                    RowLayout {
                        Layout.fillWidth: true;Layout.fillHeight: true;spacing: 0
                        Rectangle {
                            id: filesLeaf;objectName: "foldFilesLeaf"
                            visible: !fold.narrow || fold.leaf==="files"
                            Layout.fillHeight: true;Layout.fillWidth: true;Layout.preferredWidth: fold.width*.54
                            color: Theme.surface;radius: Theme.corner(6);border.color: Theme.border
                            ColumnLayout {
                                anchors.fill: parent;anchors.margins: 11;spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true;Layout.preferredHeight: 26
                                    Text {text: Fold.state.limited ? "Files · limited list" : "Files";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true;elide: Text.ElideRight}
                                    OrbitButton {text: "↑";quiet: true;implicitWidth: 26;implicitHeight: 26;hint: "Parent folder";enabled: !Fold.state.busy;onClicked: Fold.parentFolder()}
                                    OrbitButton {text: "↻";quiet: true;implicitWidth: 26;implicitHeight: 26;hint: "Refresh folder";enabled: !Fold.state.busy;onClicked: Fold.refresh()}
                                }
                                OrbitField {
                                    id: folderPath;objectName: "foldFolderPath";Layout.fillWidth: true;implicitHeight: 29;leftPadding: 8;rightPadding: 8;font.pixelSize: Theme.fontSize(11)
                                    placeholderText: "Folder path"
                                    Component.onCompleted: text=Fold.state.folder || ""
                                    onActiveFocusChanged: if(!activeFocus)text=Fold.state.folder || ""
                                    onAccepted: {Fold.setFolder(text);focus=false;}
                                    Connections {target: Fold;function onChanged(){if(!folderPath.activeFocus)folderPath.text=Fold.state.folder || "";}}
                                }
                                ListView {
                                    id: files;objectName: "foldFileList";Layout.fillWidth: true;Layout.fillHeight: true
                                    model: Fold.items;clip: true;reuseItems: true;cacheBuffer: 0;spacing: 2
                                    boundsBehavior: Flickable.StopAtBounds;activeFocusOnTab: true;keyNavigationEnabled: true
                                    onCurrentIndexChanged: if(activeFocus && currentIndex>=0 && currentIndex<count)Fold.select(Fold.items[currentIndex].id)
                                    Keys.onReturnPressed: if(currentIndex>=0 && currentIndex<count)fold.openItem(Fold.items[currentIndex])
                                    delegate: Rectangle {
                                        id: fileRow;objectName: "foldFileRow"
                                        required property var modelData;required property int index
                                        width: files.width;height: Theme.compact ? 46 : 52;radius: Theme.corner(4)
                                        color: modelData.id===Fold.state.selectedId ? Theme.raised : fileHit.containsMouse ? Theme.hover : "transparent"
                                        Rectangle {width: 2;anchors.top: parent.top;anchors.bottom: parent.bottom;color: Theme.accent;visible: modelData.id===Fold.state.selectedId}
                                        RowLayout {
                                            anchors.fill: parent;anchors.leftMargin: 10;anchors.rightMargin: 8;spacing: 9
                                            Image {Layout.preferredWidth: 23;Layout.preferredHeight: 23;source: "image://icons/"+(modelData.isDir || modelData.kind==="folder" ? "folder" : "text-x-generic");sourceSize: Qt.size(24,24);fillMode: Image.PreserveAspectFit}
                                            ColumnLayout {
                                                Layout.fillWidth: true;spacing: 3
                                                Text {text: fileRow.modelData.name;Layout.fillWidth: true;elide: Text.ElideMiddle;color: Theme.text;font.pixelSize: Theme.fontSize(12);textFormat: Text.PlainText}
                                                Text {text: fileRow.modelData.isDir || fileRow.modelData.kind==="folder" ? "Folder" : fileRow.modelData.size!==undefined ? fileRow.modelData.size+" bytes" : "File";color: Theme.muted;font.pixelSize: Theme.fontSize(10)}
                                            }
                                        }
                                        MouseArea {
                                            id: fileHit;anchors.fill: parent;hoverEnabled: true;acceptedButtons: Qt.LeftButton | Qt.RightButton
                                            onClicked: mouse => {files.currentIndex=index;Fold.select(modelData.id);if(mouse.button===Qt.RightButton)Orbit.openPanelContext(fileHit,"fold-file",modelData.id,mouse.x,mouse.y);}
                                            onDoubleClicked: fold.openItem(modelData)
                                        }
                                        Accessible.name: modelData.name;Accessible.role: Accessible.Button
                                        Accessible.onPressAction: {Fold.select(modelData.id);fold.openItem(modelData);}
                                    }
                                    Text {anchors.centerIn: parent;width: parent.width-20;visible: files.count===0;text: Fold.state.busy ? "Reading folder…" : "This folder is empty";horizontalAlignment: Text.AlignHCenter;wrapMode: Text.Wrap;color: Theme.muted;font.pixelSize: Theme.fontSize(12)}
                                }
                                Rectangle {Layout.fillWidth: true;implicitHeight: 1;color: Theme.border}
                                RowLayout {
                                    Layout.fillWidth: true;spacing: 7
                                    Text {text: fold.selectedItem.name || "Select a file";Layout.fillWidth: true;elide: Text.ElideMiddle;color: Theme.muted;font.pixelSize: Theme.fontSize(10);textFormat: Text.PlainText}
                                }
                            }
                        }
                        Item {Layout.preferredWidth: fold.narrow ? 0 : 12}
                        Rectangle {
                            id: notesLeaf;objectName: "foldNotesLeaf"
                            visible: !fold.narrow || fold.leaf==="notes"
                            Layout.fillHeight: true;Layout.fillWidth: true;Layout.preferredWidth: fold.width*.46
                            color: Theme.surface;radius: Theme.corner(6);border.color: Theme.border
                            ColumnLayout {
                                anchors.fill: parent;anchors.margins: 12;spacing: 8
                                RowLayout {Layout.fillWidth: true;Layout.preferredHeight: 26
                                    Text {text: "Notes";color: Theme.text;font.pixelSize: Theme.fontSize(12);Layout.fillWidth: true}
                                    Text {text: "LOCAL";color: Theme.faint;font.pixelSize: Theme.fontSize(9);font.letterSpacing: 1}
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
                                Text {text: "SAVED ON THIS COMPUTER";color: Theme.faint;font.pixelSize: Theme.fontSize(9);font.letterSpacing: .6}
                            }
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
