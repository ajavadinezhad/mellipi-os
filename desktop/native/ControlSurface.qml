import QtQuick 2.15
import "."

Rectangle {
    id: surface
    property bool controlEnabled: true
    property bool focused: false
    property bool hovered: false
    property bool pressed: false
    property bool primary: false
    property bool quiet: false
    property bool field: false
    property bool animate: false

    readonly property color targetFill: {
        if (primary && controlEnabled) {
            // Tint away from the label color, so hover and press cannot
            // reduce its contrast or swap black and white during the fade.
            const shade = 1 - Theme.accentText.r;
            if (pressed) return Qt.tint(Theme.accent, Qt.rgba(shade, shade, shade, .12));
            return hovered ? Qt.tint(Theme.accent, Qt.rgba(shade, shade, shade, .06)) : Theme.accent;
        }
        if (!controlEnabled) return quiet ? "transparent" : Theme.background;
        if (pressed) return Theme.selectedSurface;
        if (hovered && !field) return Theme.hover;
        if (field) return Theme.background;
        return quiet ? "transparent" : Theme.raised;
    }
    readonly property color foreground: !controlEnabled ? Theme.disabled
        : primary ? Theme.accentText : Theme.text
    radius: Theme.corner(Theme.compact ? 8 : 10)
    color: targetFill
    border.width: focused && controlEnabled && (!field || Theme.highContrast) ? 2
        : field || (Theme.highContrast && !quiet && !primary) ? 1 : 0
    border.color: !controlEnabled ? Theme.border
        : focused ? primary ? foreground : Theme.focusColor : Theme.controlBorder

    Behavior on color {
        enabled: surface.animate && !Theme.reducedMotion
        ColorAnimation { duration: surface.pressed ? Math.min(60, Theme.motion) : Theme.motion }
    }
}
