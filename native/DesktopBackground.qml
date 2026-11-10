import QtQuick 2.15
import "."
Rectangle {
    color: Orbit.appearance.wallpaper==="solid" ? Orbit.appearance.backgroundColor : Theme.background
    Rectangle {
        anchors.fill: parent;visible: Orbit.appearance.wallpaper==="dusk"
        gradient: Gradient {
            GradientStop {position: 0;color: Theme.light ? "#dce6f7" : Theme.black ? "#07090c" : "#1c213d"}
            GradientStop {position: 1;color: Theme.light ? "#f2dcd3" : Theme.black ? "#161c24" : "#493343"}
        }
    }
    Image {
        objectName: "wallpaperImage";anchors.fill: parent
        source: {
            var style=Orbit.appearance.wallpaper;
            if(Orbit.appearance.themeWallpaper)return Qt.resolvedUrl(Orbit.appearance.themeWallpaper);
            if(style==="fold" || (style==="auto" && Theme.fold))return Qt.resolvedUrl(Theme.light ? "wallpaper-spine-light.svg" : Theme.black ? "wallpaper-spine-black.svg" : "wallpaper-spine-dark.svg");
            if(style==="orbit" || (style==="auto" && !Theme.economy))return Qt.resolvedUrl(Theme.light ? "wallpaper-light.svg" : Theme.black ? "wallpaper-black.svg" : "wallpaper.svg");
            return "";
        }
        sourceSize: Qt.size(width,height);fillMode: Image.PreserveAspectCrop;smooth: true
    }
}
