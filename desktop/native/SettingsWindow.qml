import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
Window {
    id: settingsWindow
    objectName: "settingsApplicationWindow"
    title: "Settings — Mellipi"
    width: 760; height: 620; minimumWidth: 480; minimumHeight: 420
    visible: true
    flags: Qt.Window | Qt.FramelessWindowHint
    color: "transparent"
    property bool wasMaximized: false
    onVisibilityChanged: {
        if(settingsWindow.visibility!==Window.Minimized)
            wasMaximized=settingsWindow.visibility===Window.Maximized;
        SettingsConnection.setVisible(settingsWindow.visible && settingsWindow.visibility!==Window.Minimized);
    }
    function toggleMaximized() {
        if(settingsWindow.visibility===Window.Maximized)settingsWindow.showNormal();
        else settingsWindow.showMaximized();
    }
    Rectangle {objectName:"settingsWindowBackground";anchors.fill:parent;color:Theme.background;radius:settingsWindow.visibility===Window.Maximized ? 0 : Theme.corner(16);border.width:Orbit.appearance.matchWindows ? 1 : Theme.surfaceOutline;border.color:Orbit.appearance.matchWindows && settingsWindow.active && !Theme.highContrast ? Theme.accent : Theme.border}
    ColumnLayout {
        anchors.fill:parent;anchors.margins:Theme.extraCompact ? 6 : Theme.compact ? 8 : 12;spacing:Theme.extraCompact ? 5 : 8
        Item {
            id: titlebar
            objectName: "settingsWindowTitlebar"
            Layout.fillWidth:true;Layout.preferredHeight:Theme.extraCompact ? 30 : Theme.compact ? 36 : 42
            MouseArea {
                anchors.fill:parent
                onDoubleClicked: settingsWindow.toggleMaximized()
            }
            DragHandler {
                target: null
                onActiveChanged: if(active)settingsWindow.startSystemMove()
            }
            Text {
                anchors.left:parent.left;anchors.leftMargin:10;anchors.verticalCenter:parent.verticalCenter
                text:"Settings";color:Theme.text;font.pixelSize:Theme.fontSize(13);font.weight:Font.Medium
            }
            Row {
                anchors.right:parent.right;anchors.verticalCenter:parent.verticalCenter;spacing:4
                ToolButton {
                    objectName:"settingsMinimize";text:"−";Accessible.name:"Minimize Settings";width:32;height:30
                    onClicked:settingsWindow.showMinimized()
                    contentItem:Text{text:parent.text;color:Theme.text;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter}
                    background:Rectangle{radius:Theme.corner(6);color:parent.hovered?Theme.hover:"transparent";border.width:parent.activeFocus?2:0;border.color:Theme.focusColor}
                }
                ToolButton {
                    objectName:"settingsMaximize";text:settingsWindow.visibility===Window.Maximized?"❐":"□"
                    Accessible.name:settingsWindow.visibility===Window.Maximized?"Restore Settings":"Maximize Settings"
                    width:32;height:30
                    onClicked: {
                        settingsWindow.toggleMaximized();
                    }
                    contentItem:Text{text:parent.text;color:Theme.text;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter}
                    background:Rectangle{radius:Theme.corner(6);color:parent.hovered?Theme.hover:"transparent";border.width:parent.activeFocus?2:0;border.color:Theme.focusColor}
                }
                ToolButton {
                    objectName:"settingsClose";text:"×";Accessible.name:"Close Settings";width:32;height:30
                    onClicked:settingsWindow.close()
                    contentItem:Text{text:parent.text;color:Theme.text;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter}
                    background:Rectangle{radius:Theme.corner(6);color:parent.hovered?Theme.hover:"transparent";border.width:parent.activeFocus?2:0;border.color:Theme.focusColor}
                }
            }
        }
        Rectangle {Layout.fillWidth:true;Layout.preferredHeight:1;color:Theme.separator}
        SystemPanel {Layout.fillWidth:true;Layout.fillHeight:true;Layout.margins:8}
        Text {
            visible:!!Orbit.notice;Layout.fillWidth:true;Layout.leftMargin:8;Layout.rightMargin:8
            text:Orbit.notice;color:Theme.muted;font.pixelSize:Theme.fontSize(10);wrapMode:Text.Wrap;textFormat:Text.PlainText
        }
    }
    Repeater {
        model:[{edge:Qt.LeftEdge,x:0,y:8,w:5,h:settingsWindow.height-16},{edge:Qt.RightEdge,x:settingsWindow.width-5,y:8,w:5,h:settingsWindow.height-16},{edge:Qt.TopEdge,x:8,y:0,w:settingsWindow.width-16,h:5},{edge:Qt.BottomEdge,x:8,y:settingsWindow.height-5,w:settingsWindow.width-16,h:5},{edge:Qt.TopEdge|Qt.LeftEdge,x:0,y:0,w:8,h:8},{edge:Qt.TopEdge|Qt.RightEdge,x:settingsWindow.width-8,y:0,w:8,h:8},{edge:Qt.BottomEdge|Qt.LeftEdge,x:0,y:settingsWindow.height-8,w:8,h:8},{edge:Qt.BottomEdge|Qt.RightEdge,x:settingsWindow.width-8,y:settingsWindow.height-8,w:8,h:8}]
        MouseArea {
            required property var modelData
            x:modelData.x;y:modelData.y;width:modelData.w;height:modelData.h
            enabled:settingsWindow.visibility!==Window.Maximized
            cursorShape: modelData.edge===Qt.LeftEdge || modelData.edge===Qt.RightEdge ? Qt.SizeHorCursor : modelData.edge===Qt.TopEdge || modelData.edge===Qt.BottomEdge ? Qt.SizeVerCursor : modelData.edge===(Qt.TopEdge|Qt.LeftEdge) || modelData.edge===(Qt.BottomEdge|Qt.RightEdge) ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
            onPressed:settingsWindow.startSystemResize(modelData.edge)
        }
    }
}
