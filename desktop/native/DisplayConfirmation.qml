import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."

Rectangle {
    id: confirmation
    objectName: "displayConfirmation"
    readonly property var state: typeof DisplayControls === "undefined" ? ({}) : DisplayControls.state
    visible: !!state.pending
    onVisibleChanged: if (visible) Qt.callLater(function() {
        if (confirmation.visible && revertButton.enabled)
            revertButton.forceActiveFocus(Qt.TabFocusReason)
    })
    color: Theme.selectedSurface
    radius: Theme.corner(8)
    implicitHeight: contents.implicitHeight + 16
    GridLayout {
        id: contents
        anchors.fill: parent
        anchors.margins: 8
        columns: width >= Math.ceil(460 * Theme.textScale) ? 3 : 2
        Text {
            objectName: "displayCountdown"
            Layout.columnSpan: contents.columns === 2 ? 2 : 1
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: "Keep these display settings? Reverting in " + (confirmation.state.secondsRemaining || 0) + " seconds."
            wrapMode: Text.Wrap
            color: Theme.text
            font.pixelSize: Theme.labelSize
        }
        OrbitButton {
            id: revertButton
            objectName: "displayRevert"
            text: "Revert"
            enabled: confirmation.visible && !confirmation.state.busy
            onClicked: DisplayControls.revert()
        }
        OrbitButton {
            objectName: "displayKeep"
            text: "Keep settings"
            accent: true
            enabled: confirmation.visible && !confirmation.state.busy
            onClicked: DisplayControls.confirm()
        }
    }
}
