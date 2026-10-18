"""Keep the packaging checkout clean while retaining reproducible build inputs."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[3]


class LayoutTests(unittest.TestCase):
    def test_tracked_root_has_only_documentation_license_and_github(self):
        tracked=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z']).split(b'\0')
        roots={name.decode().split('/')[0] for name in tracked if name}
        self.assertEqual(roots,{'.github','LICENSE','README.md'})

    def test_native_features_are_a_patch_queue_not_vendored_source(self):
        helpers=ROOT/'.github/workflows/ctr'
        patches=list((helpers/'patches').glob('*.patch'))
        self.assertTrue(patches)
        self.assertLess(sum(p.stat().st_size for p in patches),500_000)
        self.assertFalse((ROOT/'src').exists())
        self.assertFalse((ROOT/'gpu').exists())
        self.assertTrue((helpers/'materialize.py').is_file())
        self.assertTrue((helpers/'arch/PKGBUILD').is_file())


if __name__=='__main__':unittest.main()
