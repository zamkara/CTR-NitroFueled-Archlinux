"""Native release validation and explicit update checks, using synthetic responses."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'launcher'))
import native_update as update


def release():
    tag = 'arch-' + 'a' * 40
    names = ['ctr-nitrofueled-0.r300.gaaaaaaaaaaaa-1-x86_64.pkg.tar.zst', 'install.sh', 'SHA256SUMS']
    return {'tag_name': tag, 'draft': False, 'prerelease': False, 'assets': [
        {'name': n, 'browser_download_url': f'https://github.com/{update.REPOSITORY}/releases/download/{tag}/{n}'}
        for n in names]}


class UpdateTests(unittest.TestCase):
    def test_stable_release_has_verified_asset_locations(self):
        self.assertEqual(update.release_info(release())['version'], '0.r300.gaaaaaaaaaaaa-1')

    def test_incomplete_or_untrusted_releases_are_rejected(self):
        for mutation in ('draft', 'prerelease', 'missing', 'foreign', 'duplicate', 'tag'):
            with self.subTest(mutation=mutation):
                data = release()
                if mutation in ('draft', 'prerelease'):
                    data[mutation] = True
                elif mutation == 'missing':
                    data['assets'].pop()
                elif mutation == 'foreign':
                    data['assets'][0]['browser_download_url'] = 'https://example.invalid/payload'
                elif mutation == 'duplicate':
                    data['assets'].append(data['assets'][0])
                else:
                    data['tag_name'] = 'unexpected'
                with self.assertRaises(ValueError):
                    update.release_info(data)

    def test_check_compares_installed_version_and_does_not_send_local_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'build-info.json').write_text(json.dumps({'commit': 'b' * 40, 'package_version': '0.r263.gbbbbbbbbbbbb-1'}))
            for comparison, expected in (('-1', True), ('0', False), ('1', False)):
                with self.subTest(comparison=comparison), \
                     patch.object(update.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(release()).encode())) as fetch, \
                     patch.object(update.subprocess, 'run', return_value=SimpleNamespace(stdout=comparison)) as run:
                    result = update.check(folder)
                    self.assertEqual(result['update_available'], expected)
                    request = fetch.call_args.args[0]
                    self.assertEqual(request.full_url, update.API)
                    self.assertIsNone(request.data)
                    self.assertEqual(run.call_args.args[0][0], 'vercmp')

    def test_check_failure_is_returned_to_the_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'build-info.json').write_text(json.dumps({'commit': 'b' * 40, 'package_version': '1'}))
            with patch.object(update.urllib.request, 'urlopen', side_effect=TimeoutError('offline')):
                with self.assertRaises(TimeoutError):
                    update.check(folder)

    def test_installer_uses_an_existing_local_script_without_shell_interpolation(self):
        with tempfile.TemporaryDirectory(prefix='installer space ') as folder:
            with self.assertRaises(FileNotFoundError):
                update.installer_command(folder)
            (Path(folder) / 'install.sh').touch()
            self.assertEqual(update.installer_command(folder),
                             ['xdg-terminal-exec', '--', '/usr/bin/bash', str(Path(folder) / 'install.sh')])
