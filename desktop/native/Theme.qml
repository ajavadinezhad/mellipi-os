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
    readonly property color focusColor: highContrast ? themeColor("focus",accent) : legibleInk(accent,3)
    readonly property int labelSize: Math.round(14*textScale)
    readonly property int detailSize: Math.round(12*textScale)
    readonly property int headingSize: Math.round(16*textScale)
    readonly property int smallGap: 4
    readonly property int rowGap: 8
    readonly property int sectionGap: 12
    readonly property int gap: extraCompact ? 6 : compact ? 10 : 18
    readonly property int padding: extraCompact ? 12 : compact ? 18 : 28
    function corner(n) { return Orbit.appearance.corners === "square" ? 0 : Orbit.appearance.corners === "soft" ? Math.min(6,n) : n; }
    readonly property int radius: corner(compact ? 12 : 20)
    function symbolicIconSource(name, ink) {
        return "image://icons/menu/"+String(ink || accentInk).slice(1)+"/"+name;
    }
    function phosphorIconSource(name, ink, relief) {
        return "image://icons/" + (relief ? (highContrast ? "phosphor-relief-hc/" : "phosphor-relief/") : "phosphor/")
            + String(ink).slice(1) + "/" + name;
    }
    function taskbarIconSource(name, internal) {
        const glyph = internal ? "mellipi-settings" : String(name);
        return glyph.indexOf("mellipi-")===0
            ? phosphorIconSource(glyph, accentInk, true) : iconSource(name);
    }
    function iconSource(name) {
        if (String(name).indexOf("mellipi-")===0)
            return "image://icons/fold-art/"+String(accent).slice(1)+"/"+name;
        var symbolic = {
            "system-file-manager": "folder",
            "folder": "folder",
            "user-home": "user-home",
            "drive-harddisk": "drive-harddisk",
            "user-trash": "user-trash",
            "system-software-install": "system-software-install",
            "image-x-generic": "image-x-generic",
            "application-pdf": "x-office-document",
            "multimedia-player": "video-x-generic",
            "mellipi-editor": "editor",
            "mellipi-calculator": "calculator",
            "mellipi-calendar": "calendar",
            "mellipi-browser": "browser",
            "mellipi-files": "folder",
            "mellipi-software": "software",
            "mellipi-photos": "photos",
            "mellipi-pdf": "pdf",
            "mellipi-media": "media",
            "mellipi-disks": "disks",
            "mellipi-settings": "settings",
            "mellipi-desktop": "fold",
            "utilities-terminal": "utilities-terminal",
            "mellipi-terminal": "utilities-terminal",
            "preferences-system": "preferences-system"
        }[name];
        return symbolic ? symbolicIconSource(symbolic) : "image://icons/"+name;
    }
    readonly property color accent: Orbit.accentColor
    readonly property color accentInk: legibleInk(accent,4.5)
    readonly property color accentHover: Qt.lighter(accent, 1.12)
    function linear(c) { return c <= .04045 ? c/12.92 : Math.pow((c+.055)/1.055,2.4); }
    function luminance(color) { return .2126*linear(color.r)+.7152*linear(color.g)+.0722*linear(color.b); }
    function contrast(a,b) { return (Math.max(a,b)+.05)/(Math.min(a,b)+.05); }
    readonly property color accentText: luminance(accent) > .179 ? "#000000" : "#ffffff"
    readonly property color background: themeColor("background",black ? "#07090c" : Qt.tint(light ? "#eef2f6" : "#10191f", Qt.rgba(accent.r,accent.g,accent.b,.055)))
    readonly property color surface: themeColor("surface",Qt.tint(light ? "#ffffff" : black ? "#101419" : "#172329", Qt.rgba(accent.r,accent.g,accent.b,black ? .012 : .06)))
    readonly property color raised: themeColor("raised",Qt.tint(light ? "#e1e8ee" : black ? "#1a2027" : "#203037", Qt.rgba(accent.r,accent.g,accent.b,black ? .018 : .075)))
    readonly property color hover: themeColor("hover",Qt.tint(light ? "#d7e2e8" : black ? "#242d37" : "#2b3c43", Qt.rgba(accent.r,accent.g,accent.b,black ? .03 : .12)))
    readonly property color border: themeColor("border",Qt.tint(light ? "#bac8d3" : black ? "#38424d" : "#3d5058", Qt.rgba(accent.r,accent.g,accent.b,black ? .05 : .2)))
    // Keep dividers visible over raised chrome without giving them the weight of an outline.
    readonly property color separator: highContrast ? border : Qt.tint(surface, Qt.rgba(border.r,border.g,border.b,.75))
    readonly property color selectedSurface: Qt.tint(surface, Qt.rgba(accent.r,accent.g,accent.b,.16))
    readonly property var controlSurfaces: [background,surface,raised,hover].map(function(color) { return luminance(renderedColor(color)); })
    readonly property var inkSurfaces: [background,surface,raised,hover,selectedSurface].map(luminance)
    readonly property color controlBorder: legibleInk(renderedColor(border),3,controlSurfaces,true)
    function inkContrast(color, surfaces) {
        var ink = luminance(color);
        return Math.min.apply(null,surfaces.map(function(surface) { return contrast(ink,surface); }));
    }
    function renderedColor(color) {
        return Qt.rgba(Math.round(255*color.r)/255,Math.round(255*color.g)/255,
                       Math.round(255*color.b)/255,1);
    }
    function legibleInk(color, minimum, surfaces, matchRenderedChannels) {
        surfaces = surfaces || inkSurfaces;
        if (inkContrast(color,surfaces) >= minimum) return color;
        var target = light ? 0 : 1;
        var low = 0, high = 1;
        var result = Qt.rgba(target,target,target,1);
        for (var step=0; step<10; step++) {
            var mix = (low+high)/2;
            var candidate = Qt.rgba(color.r+(target-color.r)*mix,
                                    color.g+(target-color.g)*mix,
                                    color.b+(target-color.b)*mix,1);
            // Test field borders against the channel values used in the rendered UI.
            if (matchRenderedChannels) candidate = renderedColor(candidate);
            if (inkContrast(candidate,surfaces) >= minimum) {
                high = mix;
                result = candidate;
            } else {
                low = mix;
            }
        }
        return result;
    }
    readonly property int surfaceOutline: highContrast ? 1 : 0
    readonly property color text: themeColor("text",light ? "#15222d" : "#e1e8ed")
    readonly property color mutedBase: themeColor("muted",light ? "#526473" : black ? "#adb7c4" : "#a2b0bb")
    readonly property color faintBase: themeColor("faint",light ? "#647582" : black ? "#8b97a7" : "#788b9b")
    readonly property color muted: highContrast ? mutedBase : legibleInk(mutedBase,5.2)
    readonly property color faint: highContrast ? faintBase : legibleInk(faintBase,4.8)
    readonly property color disabled: light ? "#8997a3" : black ? "#667282" : "#657681"
}
