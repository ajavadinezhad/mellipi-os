import QtQuick 2.15
import QtQuick.Controls 2.15
import "."
Slider {
    id: slider;implicitHeight: Theme.extraCompact ? 24 : Theme.compact ? 30 : 36
    background: Rectangle {
        x: slider.leftPadding;y: slider.topPadding+slider.availableHeight/2-height/2;width: slider.availableWidth;height: 4;radius: 2;color: Theme.border
        Rectangle { width: slider.visualPosition*parent.width;height: parent.height;radius: 2;color: Theme.accent }
    }
    handle: Rectangle {
        x: slider.leftPadding+slider.visualPosition*(slider.availableWidth-width);y: slider.topPadding+slider.availableHeight/2-height/2
        width: 16;height: 16;radius: Theme.corner(8);color: slider.activeFocus && Theme.highContrast ? Theme.background : Theme.text;border.color: slider.activeFocus ? Theme.focusColor : Theme.border;border.width: slider.activeFocus ? 2 : 1
    }
}
