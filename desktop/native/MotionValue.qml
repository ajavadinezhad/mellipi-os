import QtQuick 2.15

// Animate a visual-only number. The owner keeps its hit target unchanged.
QtObject {
    id: transition
    property real target: 0
    property int duration: 0
    property real value: 0
    property bool ready: false

    function updateValue() {
        change.stop();
        if(!ready || duration<=0){value=target;return;}
        if(value!==target)change.restart();
    }
    onTargetChanged: updateValue()
    onDurationChanged: if(duration<=0)updateValue()
    Component.onCompleted: {value=target;ready=true;}
    property NumberAnimation change: NumberAnimation {
        target: transition
        property: "value"
        to: transition.target
        duration: transition.duration
        easing.type: Easing.OutCubic
    }
}
