from paths import ROOT
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import game_check
from test_prepare import fixture


def param_sfo(entries):
    """A minimal param.sfo with UTF-8 string entries."""
    keys = b''.join(k.encode() + b'\0' for k in entries)
    values = [v.encode() + b'\0' for v in entries.values()]
    count = len(entries)
    key_table = 20 + 16 * count
    data_table = key_table + len(keys)
    data = bytearray(struct.pack('<4sIIII', b'\0PSF', 0x101, key_table, data_table, count))
    key_off = data_off = 0
    for key, value in zip(entries, values):
        data += struct.pack('<HHIII', key_off, 0x204, len(value), len(value), data_off)
        key_off += len(key) + 1
        data_off += len(value)
    return bytes(data + keys + b''.join(values))


class GameCheckTests(unittest.TestCase):
    def game(self, title, version, eboot=None):
        path = Path(self.tmp.name)
        (path / 'sce_sys').mkdir(exist_ok=True)
        (path / 'sce_sys/param.sfo').write_bytes(param_sfo({'APP_VER': version, 'TITLE_ID': title}))
        (path / 'eboot.bin').write_bytes(fixture() if eboot is None else eboot)
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ.pop('BB_SKIP_GAME_CHECK', None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_base_game_without_the_update(self):
        game = self.game('CUSA13795', '01.00')
        self.assertEqual(game_check.problem(game), ('missing_update', 'CUSA13795', '01.00'))
        self.assertIn('01.21', game_check.explain(*game_check.problem(game)))

    def test_update_metadata_with_an_old_executable(self):
        game = self.game('CUSA13795', '01.21')
        with mock.patch.dict(game_check.OLD_IMAGES, {game_check.image_sha256(game): '01.00'}):
            self.assertEqual(game_check.problem(game)[0], 'wrong_eboot')
            self.assertIsNone(game_check.profile(game))

    def test_other_121_build_is_accepted_as_672(self):
        # The 1.21 update for firmware 6.72+: another executable, same game.
        game = self.game('CUSA13795', '01.21')
        self.assertIsNone(game_check.problem(game))
        self.assertEqual(game_check.profile(game)['name'], 'ctr')
        self.assertEqual(game_check.profile(game)['variant'], '6.72+')

    def test_other_title(self):
        # Bloodborne (bbport's game) is no longer a profile.
        self.assertEqual(game_check.problem(self.game('CUSA03173', '01.09'))[0], 'other_title')
        self.assertEqual(game_check.problem(self.game('CUSA13796', '01.21'))[0], 'other_title')

    def test_unreadable_executable(self):
        self.assertEqual(game_check.problem(self.game('CUSA13795', '01.21', b'junk'))[0], 'unreadable')

    def test_supported_image_passes(self):
        game = self.game('CUSA13795', '01.21')
        table = {game_check.image_sha256(game): game_check.SUPPORTED[game_check.SUPPORTED_IMAGE]}
        with mock.patch.object(game_check, 'SUPPORTED', table):
            self.assertIsNone(game_check.problem(game))
            self.assertEqual(game_check.profile(game)['name'], 'ctr')
            self.assertEqual(game_check.profile(game)['variant'], '5.05')
            self.assertIn('libSceNpToolkit2.prx', game_check.profile(game)['modules'])

    def test_profile_guess_with_the_check_skipped(self):
        game = self.game('CUSA13795', '01.00')
        self.assertIsNone(game_check.profile(game))
        with mock.patch.dict(os.environ, {'BB_SKIP_GAME_CHECK': '1'}):
            self.assertEqual(game_check.profile(game)['name'], 'ctr')
            self.assertIsNone(game_check.profile(self.game('CUSA03173', '01.09')))

    def test_skip_switch(self):
        os.environ['BB_SKIP_GAME_CHECK'] = '1'
        self.assertIsNone(game_check.problem(self.game('CUSA13795', '01.00')))

    def test_pkg_tool_layout_needs_preparing(self):
        # PS4 PKG Tool: Image0 holds eboot.bin and sce_module, Sc0 the sce_sys files. A copied
        # eboot.bin and param.sfo alone do not make it runnable (sce_module stays in Image0).
        game = self.game('CUSA13795', '01.21')
        (game / 'Image0').mkdir()
        (game / 'Image0/eboot.bin').write_bytes(fixture())
        self.assertEqual(game_check.problem(game)[0], 'split_layout')
        self.assertIn('Image0', game_check.explain('split_layout', '?', '?'))
        (game / 'sce_module').mkdir()
        self.assertIsNone(game_check.problem(game))

    def test_every_problem_is_explained(self):
        for kind in ('missing_update', 'wrong_eboot', 'other_title', 'unreadable'):
            self.assertIn('CUSA', game_check.explain(kind, 'CUSA13795', '01.00'))
            self.assertIn('CUSA', game_check.explain(kind, 'CUSA00000', '01.00'))



    def test_verified_cusa14876_update_is_recognized(self):
        game = self.game('CUSA14876', '01.21')
        with mock.patch.object(game_check, 'image_sha256', return_value=game_check.EU_IMAGE):
            self.assertIsNone(game_check.problem(game))
            profile = game_check.profile(game)
            self.assertEqual(profile['title'], 'CUSA14876')
            self.assertEqual(profile['name'], 'ctr')
            self.assertEqual(profile['variant'], 'validated-1.21')

    def test_unknown_cusa14876_executable_does_not_pass_by_metadata_alone(self):
        game = self.game('CUSA14876', '01.21')
        self.assertEqual(game_check.problem(game)[0], 'unrecognized_build')
        self.assertIsNone(game_check.profile(game))

    def test_cusa14876_base_requires_the_update(self):
        game = self.game('CUSA14876', '01.00')
        with mock.patch.object(game_check, 'image_sha256', return_value=game_check.EU_BASE_IMAGE):
            self.assertEqual(game_check.problem(game)[0], 'missing_update')
        game = self.game('CUSA14876', '01.21')
        with mock.patch.object(game_check, 'image_sha256', return_value=game_check.EU_BASE_IMAGE):
            self.assertEqual(game_check.problem(game)[0], 'wrong_eboot')

    def test_known_executable_must_match_the_edition_metadata(self):
        for title, image in (('CUSA13795', game_check.EU_IMAGE), ('CUSA14876', game_check.SUPPORTED_IMAGE)):
            with self.subTest(title=title):
                game = self.game(title, '01.21')
                with mock.patch.object(game_check, 'image_sha256', return_value=image):
                    self.assertEqual(game_check.problem(game)[0], 'identity_mismatch')
                    self.assertIsNone(game_check.profile(game))


if __name__ == '__main__':
    unittest.main()
