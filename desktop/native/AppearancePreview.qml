import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."

// A schematic desktop; never captures windows or alters published Theme tokens.
Rectangle {
    id: preview
    objectName:"appearancePreview"
    required property string mode
    required property bool black
    required property color accent
    required property color backgroundColor
    required property string wallpaper
    required property var themeRow
    required property bool highContrast
    required property string taskbarPosition
    required property string taskbarLength
    required property bool taskbarFloating
    required property int iconScale
    required property int desktopIconScale
    required property bool desktopIcons
    required property real textScale
    required property string density
    required property string corners
    required property bool matchWindows
    required property bool economy
    readonly property bool light: mode==="light"
    readonly property bool horizontal: taskbarPosition==="bottom"
    readonly property color surface: themeRow ? themeRow.palette.surface : light ? "#ffffff" : black ? "#101419" : "#172329"
    readonly property color raised: themeRow ? themeRow.palette.raised : light ? "#e1e8ee" : black ? "#1a2027" : "#203037"
    readonly property color line: themeRow ? themeRow.palette.border : light ? "#bac8d3" : "#3d5058"
    readonly property color ink: highContrast ? (light ? "#000000" : "#ffffff") : themeRow ? themeRow.palette.text : light ? "#15222d" : "#e1e8ed"
    readonly property color accentInk: previewInk(accent,4.5)
    function previewInk(base,minimum) {
        var backgrounds=[Theme.luminance(surface),Theme.luminance(raised)];
        if(Theme.inkContrast(base,backgrounds)>=minimum)return base;
        var endpoint=light ? 0 : 1, low=0, high=1, best=Qt.rgba(endpoint,endpoint,endpoint,1);
        for(var i=0;i<9;++i) {
            var mix=(low+high)/2;
            var trial=Qt.rgba(base.r+(endpoint-base.r)*mix,base.g+(endpoint-base.g)*mix,base.b+(endpoint-base.b)*mix,1);
            if(Theme.inkContrast(trial,backgrounds)>=minimum){high=mix;best=trial;}
            else low=mix;
        }
        return best;
    }
    readonly property int edge: taskbarFloating ? 5 : 0
    readonly property int bar: density==="extra" ? 20 : density==="compact" ? 24 : 28
    function rounding(amount) {return corners==="square" ? 0 : corners==="soft" ? Math.min(3,amount) : amount}
    implicitHeight:Math.max(125,Math.min(170,width*.40))
    clip:true;radius:rounding(9)
    color:wallpaper==="solid" ? backgroundColor : themeRow ? themeRow.background : light ? "#eef2f6" : black ? "#07090c" : "#10191f"
    Accessible.role:Accessible.Graphic
    Accessible.name:"Desktop appearance preview"
    DesktopBackground {
        anchors.fill:parent;radius:preview.radius
        style:preview.wallpaper
        themeWallpaper: {
            var row=(Orbit.themePresets || []).find(item=>item.wallpaper===preview.wallpaper);
            return row ? row.wallpaperSource : "";
        }
        light:preview.light;black:preview.black;fold:true;economy:preview.economy
        baseColor:preview.color;solidColor:preview.backgroundColor
    }
    Row {
        visible:preview.desktopIcons
        x:preview.horizontal || preview.taskbarPosition==="right" ? 10 : preview.edge+preview.bar+10
        y:10;spacing:5
        Repeater {
            model:["folder","trash"]
            Image {
                required property string modelData
                width:Math.round(13*preview.desktopIconScale/100);height:width;sourceSize:Qt.size(24,24)
                source:Theme.symbolicIconSource(modelData, preview.light ? "#232b33" : "#ffffff")
            }
        }
    }
    Rectangle {
        id: sample
        width:Math.min(200,Math.max(104,Math.round(preview.width*.57)))
        height:Math.round(preview.height*.56)
        anchors.centerIn:parent
        anchors.horizontalCenterOffset:preview.horizontal ? 0 : preview.taskbarPosition==="left" ? preview.bar/2 : -preview.bar/2
        anchors.verticalCenterOffset:preview.horizontal ? -8 : 0
        radius:preview.rounding(7);color:preview.surface
        border.width:preview.highContrast || preview.matchWindows ? 1 : 0
        border.color:preview.matchWindows ? preview.accentInk : preview.line
        ColumnLayout {
            anchors.fill:parent;anchors.margins:8;spacing:3
            RowLayout {
                Layout.fillWidth:true
                Image {Layout.preferredWidth:12;Layout.preferredHeight:12;sourceSize:Qt.size(18,18);source:Theme.symbolicIconSource("folder",preview.accentInk)}
                Text {
                    text:"Files";Layout.fillWidth:true;elide:Text.ElideRight
                    font.pixelSize:Math.round(12*preview.textScale);font.weight:Font.DemiBold;color:preview.ink
                }
                Text {text:"×";font.pixelSize:Math.round(12*preview.textScale);color:preview.ink}
            }
            Rectangle {
                Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:1
                radius:preview.rounding(4);color:preview.raised
                Text {
                    anchors.fill:parent;anchors.leftMargin:6;anchors.rightMargin:6
                    verticalAlignment:Text.AlignVCenter;text:"Projects";elide:Text.ElideRight
                    font.pixelSize:Math.round(10*preview.textScale);color:preview.ink
                }
            }
        }
    }
    Rectangle {
        id: panel
        color:preview.raised;border.color:preview.line;border.width:preview.highContrast ? 1 : 0
        radius:preview.taskbarFloating ? preview.rounding(6) : 0
        width:preview.horizontal ? Math.max(64,Math.min(preview.width-preview.edge*2,preview.taskbarLength==="fit" ? 92 : preview.width)) : preview.bar
        height:preview.horizontal ? preview.bar : Math.min(preview.height-preview.edge*2,preview.taskbarLength==="fit" ? 92 : preview.height)
        x:preview.horizontal ? Math.round((preview.width-width)/2) : preview.taskbarPosition==="right" ? preview.width-width-preview.edge : preview.edge
        y:preview.horizontal ? preview.height-height-preview.edge : Math.round((preview.height-height)/2)
        Grid {
            anchors.centerIn:parent;columns:preview.horizontal ? 3 : 1;spacing:3
            Repeater {
                model:["fold","folder","settings"]
                Image {
                    required property string modelData
                    width:Math.round(11*preview.iconScale/100);height:width;sourceSize:Qt.size(24,24)
                    source:Theme.symbolicIconSource(modelData,preview.accentInk)
                }
            }
        }
    }
}
