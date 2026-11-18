import QtQuick 2.15

// Track one compositor-local pointer gesture. The actual window moves only
// on a valid release; neither a stolen grab nor a lost source can move it.
DragHandler {
    id: gesture
    required property var spaceMap
    required property var windowData
    required property int sourceSpace
    target: null
    acceptedButtons: Qt.LeftButton
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad | PointerDevice.Stylus
    cursorShape: active ? Qt.ClosedHandCursor : Qt.OpenHandCursor
    enabled: sourceSpace >= 0 && !!windowData.id && !windowData.minimized && !Arrangements.busy
    onGrabChanged: (transition, point) => {
        if (transition === PointerDevice.GrabExclusive)
            spaceMap.startDrag(gesture, windowData, sourceSpace, point.scenePosition);
        else if (transition === PointerDevice.UngrabExclusive)
            spaceMap.releaseDrag(gesture, point.scenePosition);
        else if (transition === PointerDevice.CancelGrabExclusive)
            spaceMap.cancelDrag(gesture);
    }
    onTranslationChanged: if (active) spaceMap.updateDrag(gesture, centroid.scenePosition)
    Component.onDestruction: if (spaceMap) spaceMap.cancelDrag(gesture)
}
