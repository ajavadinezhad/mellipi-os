import QtQuick 2.15
import QtQuick.Window 2.15
import "."
import "ClockFormat.js" as ClockFormat

Window {
    id: strips
    objectName: "systemStripsSurface"
    title: "Mellipi — Workspaces and system controls"
    property string orbitOutputName: ""
    property var geometry: ({x:0,y:0,width:800,height:600})
    property date clockNow: new Date()
    property bool ready: false
    property Component systemWidget
    readonly property int edgeMargin: Math.min(8,Math.floor(width/8))
    readonly property int stripGap: Math.min(12,Math.floor(width/12))
    readonly property real usableWidth: Math.max(0,width-2*edgeMargin-stripGap)
    readonly property rect workspaceRegion: Qt.rect(spaces.x,spaces.y,spaces.width,spaces.height)
    readonly property var workspaceDropTargets: spaces.workspaceDropTargets.map(target =>
        ({id:target.id,x:target.x+spaces.x,y:target.y+spaces.y,width:target.width,height:target.height}))
    readonly property rect utilityRegion: Qt.rect(utilities.x,utilities.y,utilities.width,utilities.height)
    function syncInputRegion() {Orbit.syncSystemStripsMask(strips);}
    onWorkspaceRegionChanged: Qt.callLater(syncInputRegion)
    onUtilityRegionChanged: Qt.callLater(syncInputRegion)
    onVisibleChanged: if(visible)Qt.callLater(syncInputRegion)
    x: geometry.x; y: geometry.y; width: geometry.width; height: 46
    visible: ready
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus

    OrbitSpine {
        id: spaces
        section: "spaces"
        outputName: strips.orbitOutputName
        x: strips.edgeMargin; y: 4; height: 38
        width: Math.max(0,Math.min(preferredWorkspaceWidth,Math.floor(strips.usableWidth*.35)))
    }
    OrbitSpine {
        id: utilities
        section: "utilities"
        outputName: strips.orbitOutputName
        clockText: ClockFormat.shortTime(strips.clockNow,Orbit.appearance.clock24)
        clockNow: strips.clockNow
        x: strips.width-width-strips.edgeMargin; y: 4; height: 38
        width: Math.max(0,Math.min(preferredUtilityWidth+(strips.systemWidget ? 112 : 0),strips.usableWidth-spaces.width))
    }
    Loader {
        // Optional native widget; retain room for the existing controls first.
        x: utilities.x+10; y: utilities.y
        width: Math.max(0,utilities.utilityLeadingSpace-18);height: utilities.height
        active: strips.systemWidget !== null && width>=48
        clip: true
        sourceComponent: strips.systemWidget
    }

}
