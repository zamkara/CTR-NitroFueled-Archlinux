"""Library file operations: recovery, identity, validation and source preservation."""
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'launcher'))
import library
sys.path.insert(0, str(ROOT / 'scripts'))
import render_config


def sfo_bytes(values):
    keys = data = b''
    entries = []
    for key, value in values.items():
        value = str(value).encode() + b'\0'
        entries.append((len(keys), 0x204, len(value), len(value), len(data)))
        keys += key.encode() + b'\0'
        data += value
    offset = 20 + 16 * len(entries)
    return struct.pack('<4sIIII', b'\0PSF', 0x101, offset, offset + len(keys), len(entries)) + b''.join(struct.pack('<HHIII', *e) for e in entries) + keys + data


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.active = self.root / 'user/savedata/1/CUSA14876'
        self.backups = self.root / 'backups'

    def slot(self, root, value, name='slot'):
        (root / name).mkdir(parents=True)
        (root / name / 'data').write_text(value)
        meta = root / (name + '.sce_sys')
        meta.mkdir()
        (meta / 'param.bin').write_bytes(bytes(1328))
        return root

    def test_import_backs_up_and_replaces_complete_slot_preserving_other_slots(self):
        self.slot(self.active, 'old')
        self.slot(self.active, 'keep', 'other')
        (self.active / 'slot/obsolete').write_text('stale')
        source = self.slot(self.root / 'import', 'new')
        library.import_saves(source, self.active, self.backups, 'CUSA14876')
        self.assertEqual((self.active / 'slot/data').read_text(), 'new')
        self.assertFalse((self.active / 'slot/obsolete').exists())
        self.assertEqual((self.active / 'other/data').read_text(), 'keep')
        backup = next(self.backups.iterdir())
        self.assertEqual((backup / 'slot/data').read_text(), 'old')
        self.assertEqual((source / 'slot/data').read_text(), 'new')
        self.assertEqual(json.loads((backup / '.ctr-save.json').read_text())['title'], 'CUSA14876')

    def test_restore_replaces_all_slots_and_preserves_backup(self):
        self.slot(self.active, 'old')
        source = self.slot(self.root / 'restore', 'restored', 'restored')
        library.install_saves(source, self.active, self.backups, replace=True, title='CUSA14876')
        self.assertFalse((self.active / 'slot').exists())
        self.assertEqual((self.active / 'restored/data').read_text(), 'restored')
        self.assertTrue(any(self.backups.iterdir()))

    def test_failed_backup_leaves_active_save_untouched(self):
        self.slot(self.active, 'old')
        source = self.slot(self.root / 'import', 'new')
        with patch.object(library, 'backup', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): library.install_saves(source, self.active, self.backups)
        self.assertEqual((self.active / 'slot/data').read_text(), 'old')

    def test_publish_failure_rolls_back(self):
        self.slot(self.active, 'old')
        source = self.slot(self.root / 'import', 'new')
        rename = Path.rename
        def fail_ready(path, target):
            if path.name == 'ready': raise OSError('publication failed')
            return rename(path, target)
        with patch.object(Path, 'rename', fail_ready):
            with self.assertRaises(OSError): library.install_saves(source, self.active, self.backups)
        self.assertEqual((self.active / 'slot/data').read_text(), 'old')

    def test_unsafe_or_unrecognized_imports_cannot_overwrite_saves(self):
        self.slot(self.active, 'old')
        source = self.root / 'source'
        source.mkdir()
        for name in ('../escape', '.', '..', 'bad/name'):
            with self.assertRaises(ValueError): library.safe_name(name)
        (source / 'link').symlink_to(self.active, target_is_directory=True)
        with self.assertRaises(ValueError): library.import_saves(source, self.active, self.backups, 'CUSA14876')
        self.assertEqual((self.active / 'slot/data').read_text(), 'old')
        with self.assertRaises(ValueError): library.install_saves(self.active, self.active, self.backups)

    def test_cross_region_manifest_is_rejected(self):
        source = self.slot(self.root / 'source', 'new')
        (source / '.ctr-save.json').write_text('{"title":"CUSA13795"}')
        with self.assertRaisesRegex(ValueError, 'another game edition'):
            library.import_saves(source, self.active, self.backups, 'CUSA14876')
        self.assertFalse(self.active.exists())

    def test_decrypted_save_metadata_conversion_and_region_check(self):
        source = self.root / 'decrypted'
        (source / 'sce_sys').mkdir(parents=True)
        (source / 'save.dat').write_bytes(b'game save')
        values = {'TITLE_ID':'CUSA14876', 'SAVEDATA_DIRECTORY':'slot', 'MAINTITLE':'Title', 'SUBTITLE':'Checkpoint', 'DETAIL':'Details'}
        (source / 'sce_sys/param.sfo').write_bytes(sfo_bytes(values))
        with self.assertRaises(ValueError): library.import_saves(source, self.active, self.backups, 'CUSA13795')
        library.import_saves(source, self.active, self.backups, 'CUSA14876')
        blob = (self.active / 'slot.sce_sys/param.bin').read_bytes()
        self.assertEqual(len(blob),1328)
        self.assertEqual(blob[:128].rstrip(b'\0'),b'Title')
        self.assertEqual((self.active / 'slot/save.dat').read_bytes(), b'game save')
        self.assertFalse((self.active / 'slot/sce_sys').exists())

    def test_export_is_new_and_rejects_recursive_target(self):
        self.slot(self.active, 'old')
        out = self.root / 'export'
        library.copy_new(self.active, out)
        with self.assertRaises(ValueError): library.copy_new(self.active, out)
        with self.assertRaises(ValueError): library.copy_new(self.active, self.active / 'recursive')
        self.assertEqual((out / 'slot/data').read_text(), 'old')

    def test_dlc_validates_edition_and_preserves_original(self):
        source = self.root / 'own.pkg'
        source.write_bytes(b'fixture')
        info = {'CATEGORY':'ac','TITLE_ID':'CUSA14876','CONTENT_ID':'EP0002-CUSA14876_00-CTRDELUXEPACK001'}
        with patch.object(library.content_profile, 'pkg_param', return_value=info):
            target = library.add_dlc(source, self.root / 'dlc', 'CUSA14876')
            self.assertEqual(target.read_bytes(), b'fixture')
            with self.assertRaises(ValueError): library.add_dlc(source, self.root / 'dlc', 'CUSA14876')
            with self.assertRaises(ValueError): library.add_dlc(source, self.root / 'other', 'CUSA13795')
        self.assertTrue(source.exists())

    def test_game_preparation_merges_into_new_folder_and_preserves_sources(self):
        base, update = self.root / 'base', self.root / 'update'
        for folder, category, version in ((base,'gd','01.00'),(update,'gp','01.21')):
            (folder / 'sce_sys').mkdir(parents=True)
            (folder / 'sce_sys/param.sfo').write_bytes(sfo_bytes({'TITLE_ID':'CUSA14876','CATEGORY':category,'APP_VER':version}))
            (folder / 'eboot.bin').write_bytes(version.encode())
        (base / 'sce_module').mkdir()
        for module in library.game_check.BY_TITLE['CUSA14876']['modules']:
            (base / 'sce_module' / module).write_bytes(b'fixture module')
        with patch.object(library.game_check, 'image_sha256', return_value=library.game_check.EU_IMAGE):
            target = library.prepare_game(base, update, self.root / 'data')
        self.assertEqual((target / 'eboot.bin').read_bytes(),b'01.21')
        self.assertEqual((base / 'eboot.bin').read_bytes(),b'01.00')
        self.assertEqual((update / 'eboot.bin').read_bytes(),b'01.21')
        with patch.object(library.game_check, 'image_sha256', return_value='unverified'):
            with self.assertRaises(ValueError): library.prepare_game(base, update, self.root / 'data')
        self.assertEqual(len(list((self.root / 'data/prepared').iterdir())),1)

    def test_remove_dlc_cannot_remove_an_external_original(self):
        source = self.root / 'own.pkg'
        source.write_bytes(b'fixture')
        managed = self.root / 'dlc'
        managed.mkdir()
        with self.assertRaises(ValueError): library.remove_dlc(source, managed, 'CUSA14876')
        target = managed / 'copy.pkg'
        target.write_bytes(b'fixture')
        info = {'CATEGORY':'ac','TITLE_ID':'CUSA14876','CONTENT_ID':'EP0002-CUSA14876_00-CTRDELUXEPACK001'}
        with patch.object(library.content_profile,'pkg_param', return_value=info):
            library.remove_dlc(target, managed, 'CUSA14876')
        self.assertFalse(target.exists())
        self.assertTrue(source.exists())

    def test_render_plan_matches_windows_resolution_and_memory(self):
        for value in ('480','720','1440','1620','2160'):
            neo, memory, label = render_config.configuration({'render_res':value})
            self.assertEqual(neo,'1')
            self.assertIn(value,label)
            self.assertEqual(memory, '7168' if value == '2160' else '0')
        self.assertEqual(render_config.configuration({'render_res':'1080'})[:2],('0','0'))
        self.assertEqual(render_config.configuration({'render_res':'2160'}, memory='8192')[1],'8192')


if __name__ == '__main__': unittest.main()
