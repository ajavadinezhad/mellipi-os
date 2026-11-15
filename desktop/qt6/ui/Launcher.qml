import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Window {
    id: root
    width: 520
    height: 310
    color: mellipiLight ? "#faf9fd" : "#232634"
    property color ink: mellipiLight ? "#252437" : "#eeeef8"
    Dialog {
        id: confirmation
        anchors.centerIn: parent
        title: "Log out of Mellipi?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        modal: true
        onAccepted: shell.logOut()
    }
    onVisibleChanged: if (visible) { search.clear(); search.forceActiveFocus() }
    Shortcut { sequence: "Escape"; onActivated: shell.toggleLauncher() }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        Label { text: "Open an app"; color: root.ink; font.pixelSize: 19 }
        Button { text: "Log out…"; visible: mellipiLogin; onClicked: confirmation.open() }
        TextField {
            id: search
            Layout.fillWidth: true
            color: root.ink
            placeholderText: "Search apps"
            onTextChanged: list.currentIndex = 0
            Keys.onDownPressed: list.incrementCurrentIndex()
            Keys.onUpPressed: list.decrementCurrentIndex()
            onAccepted: if (list.count > 0) shell.openApp(list.model[list.currentIndex])
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: shell.apps.filter(name => name.toLowerCase().includes(search.text.toLowerCase()))
            delegate: ItemDelegate {
                required property string modelData
                required property int index
                width: ListView.view.width
                highlighted: ListView.isCurrentItem
                text: modelData
                onClicked: shell.openApp(modelData)
            }
        }
    }
}
