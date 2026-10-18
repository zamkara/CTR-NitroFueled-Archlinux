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
            self.drain(0.25)
            check.assert_called_once_with(launcher.PORT_DIR)
        self.assertTrue(self.window.update_button.get_sensitive())
        self.assertTrue(self.window.install_update_button.get_visible())
        self.assertIn('Available: 2', self.window.update_row.get_subtitle())
        with patch.object(launcher.native_update, 'check', side_effect=TimeoutError('offline')):
            self.window.on_check_updates(None)
            self.drain(0.25)
        self.assertFalse(self.window.install_update_button.get_visible())
        self.assertTrue(self.window.update_button.get_sensitive())
        self.assertIn('offline', self.window.update_row.get_subtitle())
