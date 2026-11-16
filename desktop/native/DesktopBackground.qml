import QtQuick 2.15
import "."
Rectangle {
    id: backdrop
    property string style: Orbit.appearance.wallpaper || "auto"
    property string themeWallpaper: Orbit.appearance.themeWallpaper || ""
    property bool light: Theme.light
    property bool black: Theme.black
    property bool fold: Theme.fold
    property bool economy: Theme.economy
    property color baseColor: Theme.background
    property color solidColor: Orbit.appearance.backgroundColor || Theme.background
    color: style==="solid" ? solidColor : baseColor
    Rectangle {
        anchors.fill: parent;visible: backdrop.style==="dusk"
        gradient: Gradient {
            GradientStop {position: 0;color: backdrop.light ? "#dce6f7" : backdrop.black ? "#07090c" : "#1c213d"}
            GradientStop {position: 1;color: backdrop.light ? "#f2dcd3" : backdrop.black ? "#161c24" : "#493343"}
        }
    }
    Image {
        objectName: "wallpaperImage";anchors.fill: parent
        source: {
            var style=backdrop.style;
            if(backdrop.themeWallpaper)return Qt.resolvedUrl(backdrop.themeWallpaper);
            if(style==="fold" || (style==="auto" && backdrop.fold))return Qt.resolvedUrl(backdrop.light ? "wallpaper-spine-light.svg" : backdrop.black ? "wallpaper-spine-black.svg" : "wallpaper-spine-dark.svg");
            if(style==="orbit" || (style==="auto" && !backdrop.economy))return Qt.resolvedUrl(backdrop.light ? "wallpaper-light.svg" : backdrop.black ? "wallpaper-black.svg" : "wallpaper.svg");
            return "";
        }
        sourceSize: Qt.size(width,height);fillMode: Image.PreserveAspectCrop;smooth: true
    }
}
