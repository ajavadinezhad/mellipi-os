"""The secure keyboard stays local to the locker and preserves PAM sources."""
import hashlib,json,os,shutil,subprocess,tarfile,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class LockKeyboardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc') and shutil.which('pkg-config'),'Cairo build tools unavailable')
    def test_actual_c_key_mapping_tap_cancellation_and_pixels(self):
        env=dict(os.environ)
        sdk=ROOT/'.screen-lock-build/sysroot/usr'
        if (sdk/'lib/x86_64-linux-gnu/pkgconfig/cairo.pc').is_file():env['PKG_CONFIG_LIBDIR']=':'.join(str(p) for p in [sdk/'lib/x86_64-linux-gnu/pkgconfig',sdk/'share/pkgconfig'])
        if subprocess.run(['pkg-config','--exists','cairo'],env=env,check=False).returncode:self.skipTest('Cairo development package unavailable')
        with tempfile.TemporaryDirectory(prefix='mellipi-keyboard-test-') as directory:
            subprocess.run(['python3',str(ROOT/'tools/check-lock-keyboard.py'),'--output-dir',directory],env=env,check=True,capture_output=True,text=True)
            self.assertEqual(len(list(Path(directory).glob('keyboard-*.png'))),4)
    def test_built_artifact_preserves_upstream_password_and_pam_code(self):
        manifest=ROOT/'.lock-runtime/manifest.json';archive=ROOT/'.screen-lock-build/swaylock-1.8.6.tar.gz';source=ROOT/'.screen-lock-build/swaylock-1.8.6'
        if not manifest.is_file() or not archive.is_file():self.skipTest('Local reviewed locker build unavailable')
        value=json.loads(manifest.read_text());feature=value['presentationPatch'].get('lockerOwnedKeyboard')
        if not feature:self.skipTest('Old locker build; rebuild before testing keyboard provenance')
        self.assertTrue(feature['printableAscii']);self.assertFalse(feature['externalVirtualKeyboard'])
        with tarfile.open(archive) as tar:
            for name in ['pam.c','password.c','password-buffer.c','comm.c','main.c']:
                pristine=tar.extractfile('swaylock-1.8.6/'+name).read();digest=hashlib.sha256(pristine).hexdigest()
                self.assertEqual(value['presentationPatch']['authenticationSources'][name],digest)
                self.assertEqual((source/name).read_bytes(),pristine)
        self.assertEqual(hashlib.sha256((ROOT/'native/swaylock-keyboard.patch').read_bytes()).hexdigest(),feature['inputPatchSha256'])
        self.assertEqual(hashlib.sha256((ROOT/'native/lock-keyboard.h').read_bytes()).hexdigest(),feature['keyboardHeaderSha256'])
if __name__=='__main__':unittest.main()
