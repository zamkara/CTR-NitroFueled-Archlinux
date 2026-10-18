"""Direct-play startup behavior without spawning a game or a GTK window."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'launcher'))

try:
    import sacredfire_launcher as launcher
except (ImportError, ValueError):
    launcher = None


@unittest.skipIf(launcher is None, 'GTK4 and libadwaita are required')
class DirectPlayTests(unittest.TestCase):
    def test_unconfigured_shortcut_opens_setup_instead_of_exiting_silently(self):
        settings = {**launcher.DEFAULTS, 'game_dir': ''}
        with patch.object(launcher, 'load_settings', return_value=settings), \
             patch.object(launcher, 'LauncherApp') as app, \
             patch.object(launcher.os, 'execvpe') as execute:
            app.return_value.run.return_value = 0
            self.assertEqual(launcher.play(), 0)
            app.return_value.run.assert_called_once_with([])
            execute.assert_not_called()

    def test_missing_game_directory_also_opens_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = {**launcher.DEFAULTS, 'game_dir': str(Path(folder) / 'missing')}
            with patch.object(launcher, 'load_settings', return_value=settings), \
                 patch.object(launcher, 'LauncherApp') as app, \
                 patch.object(launcher.os, 'execvpe') as execute:
                app.return_value.run.return_value = 0
                self.assertEqual(launcher.play(), 0)
                app.return_value.run.assert_called_once_with([])
                execute.assert_not_called()

    def test_configured_shortcut_uses_saved_game_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'eboot.bin').write_bytes(b'fixture')
            settings = {**launcher.DEFAULTS, 'game_dir': folder, 'fullscreen': True}
            with patch.object(launcher, 'load_settings', return_value=settings), \
                 patch.object(launcher, 'LauncherApp') as app, \
                 patch.object(launcher.os, 'chdir'), \
                 patch.object(launcher.os, 'execvpe') as execute:
                launcher.play()
                app.assert_not_called()
                executable, args, env = execute.call_args.args
                self.assertEqual(executable, 'bash')
                self.assertEqual(args, ['bash', str(launcher.PORT_DIR / 'run.sh')])
                self.assertEqual(env['BB_GAME_DIR'], folder)
                self.assertEqual(env['BB_FULLSCREEN'], '1')
