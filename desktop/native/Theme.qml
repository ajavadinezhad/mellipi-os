pragma Singleton
import QtQuick 2.15
QtObject {
    readonly property bool fold: Orbit.appearance.shellLayout === "fold"
    readonly property bool compact: Orbit.compact
    readonly property bool extraCompact: Orbit.appearance.density === "extra"
    readonly property int barThickness: extraCompact ? 52 : compact ? 64 : 76
    readonly property bool economy: Orbit.economy
    readonly property bool reducedMotion: Orbit.appearance.reducedMotion
    readonly property int motion: reducedMotion ? 0 : economy ? 110 : 160
    readonly property bool light: Orbit.themeMode === "light"
    readonly property bool black: !light && Orbit.appearance.darkLevel === "black"
    readonly property real textScale: Math.max(.85,Math.min(1.5,Orbit.appearance.textScale || 1))
    readonly property var palette: Orbit.appearance.themePalette || ({})
    function themeColor(name,fallback) {return palette[name] || fallback;}
    readonly property bool highContrast: Orbit.appearance.highContrast === true
    function fontSize(n) { return Math.max(8,Math.round((extraCompact ? Math.max(8,n-1) : n)*textScale)); }
    readonly property color focusColor: themeColor("focus",accent)
    readonly property int gap: extraCompact ? 6 : compact ? 10 : 18
    readonly property int padding: extraCompact ? 12 : compact ? 18 : 28
    function corner(n) { return Orbit.appearance.corners === "square" ? 0 : Orbit.appearance.corners === "soft" ? Math.min(6,n) : n; }
    readonly property int radius: corner(compact ? 12 : 20)
    function symbolicIconSource(name) {
        return "image://icons/menu/"+String(highContrast ? text : accent).slice(1)+"/"+name;
    }
    function iconSource(name) {
        var symbolic = {
            "system-file-manager": "folder",
            "folder": "folder",
            "user-home": "user-home",
            "drive-harddisk": "drive-harddisk",
            "user-trash": "user-trash",
            "system-software-install": "system-software-install",
            "mellipi-files": "folder",
            "utilities-terminal": "utilities-terminal",
            "mellipi-terminal": "utilities-terminal",
            "preferences-system": "preferences-system"
        }[name];
        return symbolic ? symbolicIconSource(symbolic) : "image://icons/"+name;
    }
    readonly property color accent: Orbit.accentColor
    readonly property color accentHover: Qt.lighter(accent, 1.12)
    function linear(c) { return c <= .04045 ? c/12.92 : Math.pow((c+.055)/1.055,2.4); }
    readonly property color accentText: (.2126*linear(accent.r)+.7152*linear(accent.g)+.0722*linear(accent.b)) > .179 ? "#000000" : "#ffffff"
    readonly property color background: themeColor("background",black ? "#07090c" : Qt.tint(light ? "#eef2f6" : "#10191f", Qt.rgba(accent.r,accent.g,accent.b,.055)))
    readonly property color surface: themeColor("surface",Qt.tint(light ? "#ffffff" : black ? "#101419" : "#172329", Qt.rgba(accent.r,accent.g,accent.b,black ? .012 : .06)))
    readonly property color raised: themeColor("raised",Qt.tint(light ? "#e1e8ee" : black ? "#1a2027" : "#203037", Qt.rgba(accent.r,accent.g,accent.b,black ? .018 : .075)))
    readonly property color hover: themeColor("hover",Qt.tint(light ? "#d7e2e8" : black ? "#242d37" : "#2b3c43", Qt.rgba(accent.r,accent.g,accent.b,black ? .03 : .12)))
    readonly property color border: themeColor("border",Qt.tint(light ? "#bac8d3" : black ? "#38424d" : "#3d5058", Qt.rgba(accent.r,accent.g,accent.b,black ? .05 : .2)))
    readonly property color separator: highContrast ? border : Qt.tint(background, Qt.rgba(border.r,border.g,border.b,.35))
    readonly property color selectedSurface: highContrast ? raised : Qt.tint(surface, Qt.rgba(accent.r,accent.g,accent.b,.16))
    readonly property int surfaceOutline: highContrast ? 1 : 0
    readonly property color text: themeColor("text",light ? "#15222d" : "#e1e8ed")
    readonly property color muted: themeColor("muted",light ? "#526473" : black ? "#adb7c4" : "#a2b0bb")
    readonly property color faint: themeColor("faint",light ? "#647582" : black ? "#8b97a7" : "#788b9b")
    readonly property color disabled: light ? "#8997a3" : black ? "#667282" : "#657681"
}
