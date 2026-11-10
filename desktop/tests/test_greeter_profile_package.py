"""The optional full profile styles its greeter without changing PAM or selection."""
import configparser,stat,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from tests.test_desktop_package import builder

class GreeterProfilePackageTest(unittest.TestCase):
    def test_small_readable_static_assets_and_conffile_preserve_main_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            stage=builder.stage_desktop_package(Path(directory)/'stage','0.1.5')
            config=stage/'etc/lightdm/lightdm-gtk-greeter.conf.d/60-abstract.conf'
            wallpaper=stage/'usr/share/backgrounds/abstract/login.svg'
            parsed=configparser.ConfigParser(interpolation=None);parsed.read(config)
            greeter=parsed['greeter']
            self.assertEqual(greeter['background'],'/usr/share/backgrounds/abstract/login.svg')
            self.assertIn('gnome-themes-extra',(stage/'DEBIAN/control').read_text())
            self.assertNotIn('position',greeter)
            self.assertEqual(greeter['theme-name'],'Adwaita-dark');self.assertEqual(greeter['icon-theme-name'],'Adwaita')
            self.assertEqual(greeter['user-background'],'false');self.assertEqual(greeter['transition-duration'],'0')
            self.assertTrue({'~session','~a11y','~clock','~power'}.issubset(set(greeter['indicators'].split(';'))))
            self.assertNotIn('~language',greeter['indicators']);self.assertIn('%d',greeter['clock-format']);self.assertIn('%H:%M',greeter['clock-format'])
            self.assertEqual((stage/'DEBIAN/conffiles').read_text(),'/etc/lightdm/lightdm-gtk-greeter.conf.d/60-abstract.conf\n')
            self.assertFalse((stage/'etc/lightdm/lightdm.conf').exists());self.assertFalse((stage/'etc/lightdm/lightdm-gtk-greeter.conf').exists())
            self.assertFalse((stage/'etc/pam.d').exists());self.assertFalse((stage/'DEBIAN/postinst').exists())
            self.assertLess(config.stat().st_size+wallpaper.stat().st_size,10*1024)
            for asset in (config,wallpaper):self.assertEqual(stat.S_IMODE(asset.stat().st_mode),0o644)
            root=ET.parse(wallpaper).getroot();self.assertEqual(root.tag,'{http://www.w3.org/2000/svg}svg')
            for item in root.iter():self.assertNotIn(item.tag.rsplit('}',1)[-1],('script','animate','animateTransform','filter','image','foreignObject'))
            self.assertIn('Mellipi',wallpaper.read_text())
