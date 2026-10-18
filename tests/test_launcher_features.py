"""GTK integration for mapping persistence and update-check UI state."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'launcher'))
try:
    import sacredfire_launcher as launcher
    from gi.repository import Adw, Gio, Gtk, GLib
except (ImportError, ValueError):
    launcher = None


@unittest.skipIf(launcher is None, 'GTK4 and libadwaita are required')
class LauncherFeatureTests(unittest.TestCase):
    def setUp(self):
        if not Gtk.init_check():
            self.skipTest('A graphical display is required')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        (folder / 'settings.json').write_text(json.dumps({'game_dir': ''}))
        for target, value in (('CONFIG_FILE', folder / 'settings.json'), ('DATA_DIR', folder)):
            patcher = patch.object(launcher, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, {'BB_CONFIG': str(folder / 'bbport.ini')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = Adw.Application(application_id='io.github.CTRNative.T' + uuid.uuid4().hex, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.app.register(None)
        self.window = launcher.LauncherWindow(self.app)
        self.addCleanup(self.window.destroy)
        self.window.present()
        self.drain()

    def drain(self, duration=0.1):
        end = time.monotonic() + duration
        context = GLib.MainContext.default()
        while time.monotonic() < end:
            if context.pending():
                context.iteration(False)
            else:
                time.sleep(0.002)

    def wait_for_update(self):
        deadline = time.monotonic() + 3
        while not self.window.update_button.get_sensitive() and time.monotonic() < deadline:
            self.drain(0.02)
        self.assertTrue(self.window.update_button.get_sensitive())

    def test_statistics_persist_and_apply_to_direct_play(self):
        self.window.mangohud_row.set_active(True)
        self.window.stats_interval_row.set_selected(1)
        self.window.store()
        saved = launcher.load_settings()
        self.assertTrue(saved['mangohud'])
        self.assertEqual(saved['stats_interval'], '2000')
        with patch.dict(os.environ, {}, clear=True):
            env = launcher.game_environment(saved)
        self.assertEqual(env['MANGOHUD'], '1')
        self.assertIn('fps_sampling_period=2000', env['MANGOHUD_CONFIG'])
        for metric in ('fps', 'frametime', 'cpu_stats', 'gpu_stats', 'vram', 'ram'):
            self.assertIn(metric, env['MANGOHUD_CONFIG'].split(','))
        with patch.dict(os.environ, {'MANGOHUD_CONFIG': 'fps_only'}, clear=True):
            self.assertEqual(launcher.game_environment(saved)['MANGOHUD_CONFIG'], 'fps_only')

    def test_graphics_ports_and_window_mode_share_runtime_settings(self):
        self.window.render_row.set_selected(self.window.render_row.values.index('720'))
        self.window.upscale_row.set_selected(self.window.upscale_row.values.index('fsr3'))
        self.window.limit_row.set_selected(self.window.limit_row.values.index('144'))
        self.window.fullscreen_row.set_active(True)
        self.window.async_row.set_active(True)
        self.window.port_rows[2].values.append('test-controller-guid')
        self.window.port_rows[2].get_model().append('Test controller')
        self.window.port_rows[2].set_selected(1)
        self.window.store()
        values, _ = launcher.load_ini()
        for key, expected in {'render_res':'720','temporal':'fsr3','fps_limit':'144',
                              'fullscreen':'1','async_pipelines':'1','port.2':'test-controller-guid'}.items():
            self.assertEqual(values[key],expected)
        self.assertNotIn('dlss', self.window.upscale_row.values)
        self.assertEqual(launcher.game_environment(launcher.load_settings())['BB_FULLSCREEN'], '1')
        # The running game's menu is authoritative after it exits.
        values.update(fullscreen='0', fps_limit='72', render_res='1080')
        launcher.save_ini(values, [])
        class Exited:
            def wait_finish(self, _result): pass
            def get_if_exited(self): return True
            def get_exit_status(self): return 0
        self.window.on_exit(Exited(), None)
        self.assertFalse(self.window.fullscreen_row.get_active())
        self.assertEqual(launcher.combo_value(self.window.limit_row),'72')
        self.window.store()
        self.assertEqual(launcher.game_environment(launcher.load_settings())['BB_FULLSCREEN'], '0')

    def test_library_failure_and_retry_do_not_block_gtk(self):
        self.window.library_task('Fixture operation', lambda: (_ for _ in ()).throw(OSError('fixture failure')))
        deadline = time.monotonic() + 3
        while self.window.library_busy and time.monotonic() < deadline: self.drain(0.02)
        self.assertFalse(self.window.library_busy)
        self.assertTrue(self.window.library_retry.get_visible())
        # No configured game is allowed to replace the operation error with an empty-state message.
        self.assertIn('fixture failure',self.window.library_status.get_subtitle())
        self.window.library_task('Fixture operation', lambda: 'success')
        deadline = time.monotonic() + 3
        while self.window.library_busy and time.monotonic() < deadline: self.drain(0.02)
        self.assertFalse(self.window.library_retry.get_visible())
        self.assertIn('success',self.window.library_status.get_subtitle())

    def test_higher_frame_limit_enables_required_unlock_patch(self):
        self.window.limit_row.set_selected(self.window.limit_row.values.index('144'))
        self.assertTrue(self.window.patch_rows['patch_60fps'].get_active())
        self.window.store()
        values, _ = launcher.load_ini()
        self.assertEqual((values['fps_limit'], values['patch_60fps']),('144','1'))
        self.window.patch_rows['patch_60fps'].set_active(False)
        self.assertEqual(launcher.combo_value(self.window.limit_row),'30')
        self.window.patch_rows['patch_60fps'].set_active(True)
        self.assertEqual(launcher.combo_value(self.window.limit_row),'60')

    def test_library_lists_managed_dlc_and_additional_patch_switches(self):
        directory = launcher.DATA_DIR / 'patches'
        directory.mkdir()
        (directory / 'extra.xml').write_text('<Patch><TitleID><ID>CUSA14876</ID></TitleID><Metadata Name="Extra" AppVer="01.21" AppElf="eboot.bin"><PatchList/></Metadata></Patch>')
        dlc = launcher.DATA_DIR / 'dlc'
        dlc.mkdir()
        (dlc / 'own.pkg').write_bytes(b'fixture')
        with patch.object(launcher.game_check, 'sfo_info', return_value={'TITLE_ID':'CUSA14876'}), \
             patch.object(launcher.library.content_profile,'find_addons',return_value=[('CTRDELUXEPACK001','Deluxe','own.pkg')]):
            self.window.refresh_library()
        row = self.window.dlc_list_rows[0]
        self.assertIsInstance(row,Adw.SwitchRow)
        row.set_active(False)
        self.assertIn('CTRDELUXEPACK001',launcher.load_settings()['dlc_disabled'])
        extra = self.window.extra_patch_rows[0]
        self.assertIsInstance(extra,Adw.SwitchRow)
        extra.set_active(True)
        config = json.loads((launcher.DATA_DIR / 'patches.json').read_text())
        self.assertIn('extra.xml/Extra',config['enabled'])

    def test_recording_captures_physical_key_and_escape_cancels(self):
        self.window.on_edit_binding(None, 'key', 'cross')
        dialog = self.window.get_visible_dialog()
        def buttons(widget):
            result = [widget] if isinstance(widget,Gtk.Button) and widget.get_label() == 'Record' else []
            child = widget.get_first_child()
            while child:
                result.extend(buttons(child)); child = child.get_next_sibling()
            return result
        records = buttons(dialog.get_extra_child())
        self.assertEqual(len(records),4)
        records[0].emit('clicked')
        self.assertTrue(dialog.record_controller.emit('key-pressed', launcher.Gdk.KEY_f, 41, 0))
        drops = self.dropdowns(dialog.get_extra_child())
        options = [''] + list(launcher.control_bindings.choices('key'))
        self.assertEqual(options[drops[0].get_selected()],'F')
        records[0].emit('clicked')
        self.assertTrue(dialog.record_controller.emit('key-pressed', launcher.Gdk.KEY_Escape, 9, 0))
        self.assertEqual(options[drops[0].get_selected()],'F')
        dialog.emit('response','save');dialog.force_close()
        self.assertEqual(launcher.load_ini()[0]['key.cross'],'F')

    def dropdowns(self, widget):
        result = [widget] if isinstance(widget, Gtk.DropDown) else []
        child = widget.get_first_child()
        while child:
            result.extend(self.dropdowns(child))
            child = child.get_next_sibling()
        return result

    def test_mapping_dialog_saves_only_selected_controls_and_reset_preserves_other_settings(self):
        launcher.ini_path().write_text('# keep this comment\nshow_fps=1\npad.cross=x\n')
        self.window.stack.set_visible_child_name('controls')
        self.window.on_edit_binding(None, 'key', 'cross')
        dialog = self.window.get_visible_dialog()
        self.assertIsNotNone(dialog)
        dropdowns = self.dropdowns(dialog.get_extra_child())
        self.assertEqual(len(dropdowns), 4)
        options = [''] + list(launcher.control_bindings.choices('key'))
        dropdowns[0].set_selected(options.index('F'))
        dialog.emit('response', 'save')
        dialog.force_close()
        self.drain()
        values, lines = launcher.load_ini()
        self.assertEqual(values['key.cross'], 'F')
        self.assertEqual(values['pad.cross'], 'x')
        self.assertEqual(values['show_fps'], '1')
        self.assertIn('# keep this comment', lines)
        self.window.on_reset_bindings(None, 'key')
        dialog = self.window.get_visible_dialog()
        dialog.emit('response', 'reset')
        dialog.force_close()
        self.drain()
        values, _ = launcher.load_ini()
        self.assertNotIn('key.cross', values)
        self.assertEqual(values['pad.cross'], 'x')
        self.assertEqual(values['show_fps'], '1')

    def test_manual_update_check_and_retry_leave_ui_responsive(self):
        result = {'installed': '1', 'version': '2', 'update_available': True}
        with patch.object(launcher.native_update, 'check', return_value=result) as check:
            self.window.on_check_updates(None)
            self.wait_for_update()
            check.assert_called_once_with(launcher.PORT_DIR)
        self.assertTrue(self.window.update_button.get_sensitive())
        self.assertTrue(self.window.install_update_button.get_visible())
        self.assertIn('Available: 2', self.window.update_row.get_subtitle())
        with patch.object(launcher.native_update, 'check', side_effect=TimeoutError('offline')):
            self.window.on_check_updates(None)
            self.wait_for_update()
        self.assertFalse(self.window.install_update_button.get_visible())
        self.assertTrue(self.window.update_button.get_sensitive())
        self.assertIn('offline', self.window.update_row.get_subtitle())
