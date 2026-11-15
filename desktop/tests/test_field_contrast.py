"""Verify the actual QML text field outline on each theme surface."""
from pathlib import Path
import unittest
from qt_compat import QApplication, QColor, QObject, Property, QQmlApplicationEngine, QUrl, QT5, QT6_WAYLAND
if QT5:
    from PyQt5.QtQml import QQmlComponent
elif QT6_WAYLAND:
    from PyQt6.QtQml import QQmlComponent
else:
    from PySide6.QtQml import QQmlComponent
from app_palette import colors, contrast_palette, contrast_ratio
from theme_catalog import presets

NATIVE = Path(__file__).resolve().parents[1] / 'native'
class Stub(QObject):
    appearance = Property('QVariantMap', lambda self: self.current, constant=True)

    def __init__(self, appearance):
        super().__init__()
        self.current = appearance
    themeMode = Property(str, lambda self: self.current['mode'], constant=True)
    accentColor = Property(QColor, lambda self: QColor(self.current['accent']), constant=True)
    compact = Property(bool, lambda self: True, constant=True)
    economy = Property(bool, lambda self: True, constant=True)

VARIANTS = [(r['name'], dict(mode=r['mode'], darkLevel=r['darkLevel'], accent=r['accent'], themePalette=r['palette'])) for r in presets()]
VARIANTS += [(f'Custom {mode} {level} {accent}', dict(mode=mode, darkLevel=level, accent=accent, themePalette={}))
             for mode,level in [('light','normal'),('dark','normal'),('dark','black')]
             for accent in ('#a9d9c3','#000000','#ffffff','#ff0000','#00ff00','#0000ff')]
FIELD_PROBE = b'''import QtQuick 2.15
import QtQuick.Window 2.15
import "."
Window {
    visible: true
    width: 300
    height: 100
    property alias field: field
    property color fieldBorder: field.background.border.color
    property int fieldBorderWidth: field.background.border.width
    property color expectedFocus: Theme.focusColor
    property color decoration: Theme.border
    property color base: Theme.background
    property color panel: Theme.surface
    property color raised: Theme.raised
    property color hover: Theme.hover
    Item { id: other; focus: true }
    OrbitField { id: field; x: 10; y: 10 }
}
'''
def distance(a,b):
    return max(abs(x-y) for x,y in zip(QColor(a).getRgb(), QColor(b).getRgb()))
class FieldContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_text_field_border_contrast_and_focus(self):
        for name, normal in VARIANTS:
            for high_contrast in (False, True):
                with self.subTest(theme=name, high_contrast=high_contrast):
                    appearance = dict(normal, highContrast=high_contrast, reducedMotion=True)
                    if high_contrast:
                        appearance['themePalette'] = contrast_palette(appearance, appearance['themePalette'])
                    self.check_field(appearance)

    def test_high_contrast_preserves_theme_surfaces_and_accent(self):
        for name, normal in VARIANTS[:len(presets())]:
            with self.subTest(theme=name):
                before = dict(normal, highContrast=False)
                after = dict(normal, highContrast=True,
                             themePalette=contrast_palette(normal, normal['themePalette']))
                def tokens(appearance):
                    return colors(type('Preferences', (), {'appearance': lambda self: appearance})())
                standard, high = tokens(before), tokens(after)
                for key in ('background', 'surface', 'raised', 'hover', 'accent',
                            'accent_ink', 'selected_surface'):
                    self.assertEqual(high[key], standard[key], key)
                for key in ('background', 'surface', 'raised', 'hover'):
                    self.assertGreaterEqual(contrast_ratio(high['border'], high[key]), 3)

    def check_field(self, appearance):
        orbit = Stub(appearance)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('Orbit', orbit)
        component = QQmlComponent(engine)
        component.setData(FIELD_PROBE, QUrl.fromLocalFile(str(NATIVE / 'field-probe.qml')))
        window = component.create()
        try:
            self.assertIsNotNone(window, [error.toString() for error in component.errors()])
            self.app.processEvents()
            field = window.property('field')
            self.assertFalse(field.property('activeFocus'))
            border = window.property('fieldBorder').name()
            app_palette = colors(type('Preferences', (), {'appearance': lambda self: appearance})())
            self.assertLessEqual(distance(border, app_palette['control_border']), 3)
            for background in ('base', 'panel', 'raised', 'hover'):
                self.assertGreaterEqual(contrast_ratio(border, window.property(background).name()), 3)
            field.setProperty('focus', True)
            self.app.processEvents()
            self.assertTrue(field.property('activeFocus'))
            self.assertEqual(window.property('fieldBorder'), window.property('expectedFocus'))
            self.assertEqual(window.property('fieldBorderWidth'), 2 if appearance['highContrast'] else 1)
            field.setProperty('enabled', False)
            self.app.processEvents()
            self.assertEqual(window.property('fieldBorder'), window.property('decoration'))
        finally:
            if QT5:
                from PyQt5.sip import delete
            elif QT6_WAYLAND:
                from PyQt6.sip import delete
            else:
                from shiboken6 import delete
            if window is not None:
                window.close()
                delete(window)
            delete(component)
            delete(engine)
