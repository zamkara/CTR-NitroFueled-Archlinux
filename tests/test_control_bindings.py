"""Runtime-compatible keyboard/gamepad names, validation and scoped resets."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'launcher'))
import control_bindings as controls


class BindingTests(unittest.TestCase):
    def test_actions_match_the_runtime(self):
        source = (ROOT / 'src/runtime_pad.c').read_text()
        table = source.split('input_names[IN_COUNT]={', 1)[1].split('};', 1)[0]
        actions = re.findall(r'"([a-z0-9_]+)"', table)
        self.assertEqual(set(controls.KEY_DEFAULTS), set(actions))
        self.assertEqual(set(controls.PAD_DEFAULTS), set(actions[:actions.index('move_up')]))

    def test_reset_keeps_other_controls_settings_and_comments(self):
        values = {'key.cross': 'F', 'pad.cross': 'x', 'show_fps': '1', 'custom.setting': 'yes'}
        lines = ['# key.cross=note', 'key.cross=F', 'pad.cross=x', 'show_fps=1', 'custom.setting=yes']
        reset, kept = controls.reset(values, lines, 'key')
        self.assertNotIn('key.cross', reset)
        self.assertEqual(reset['pad.cross'], 'x')
        self.assertEqual(reset['custom.setting'], 'yes')
        self.assertIn('# key.cross=note', kept)
        self.assertNotIn('key.cross=F', kept)
        self.assertEqual(controls.binding(reset, 'key', 'cross'), 'Space')

    def test_explicit_unbound_is_distinct_from_default(self):
        self.assertEqual(controls.binding({}, 'key', 'cross'), 'Space')
        self.assertEqual(controls.binding({'key.cross': ''}, 'key', 'cross'), '')

    def test_defaults_and_custom_values_are_valid_sdl_names(self):
        try:
            controls.sdl()
        except OSError:
            self.skipTest('SDL3 is required')
        for prefix in ('key', 'pad'):
            for action, value in controls.defaults(prefix).items():
                with self.subTest(prefix=prefix, action=action):
                    self.assertEqual(controls.normalized(prefix, value.split(',')), value)
        self.assertEqual(controls.normalized('key', ['Space', 'F', 'Space', '']), 'Space,F')
        self.assertEqual(controls.normalized('key', ['', '', '', '']), '')
        for values in (['not-a-key'], ['A', 'B', 'C', 'D', 'E']):
            with self.assertRaises(ValueError):
                controls.normalized('key', values)


    def test_displayed_defaults_match_compiled_runtime_constants(self):
        compiler = shutil.which('cc')
        if not compiler or not Path('/usr/include/SDL3/SDL_scancode.h').is_file():
            self.skipTest('C compiler and SDL3 headers are required')
        source = (ROOT / 'src/runtime_pad.c').read_text().split('static void bind_defaults(void)', 1)[1].split('    memset(bindings', 1)[0]
        keyboard, pads = source.split('} pads[]={', 1)
        rows = []
        for prefix, text in (('key', keyboard), ('pad', pads)):
            for action, constant in re.findall(r'\{IN_([A-Z0-9_]+),\s*(SDL_[A-Z0-9_]+|PAD_[A-Z0-9_]+)\}', text):
                rows.append((prefix, action.lower(), constant))
        lines = ['#include <stdio.h>', '#include <SDL3/SDL_scancode.h>', '#include <SDL3/SDL_gamepad.h>', 'int main(void) {']
        for prefix, action, constant in rows:
            if constant.startswith('SDL_'):
                lines.append(f'printf("{prefix} {action} {constant} %d\\n", (int){constant});')
        lines += ['return 0;', '}']
        with tempfile.TemporaryDirectory() as folder:
            executable = str(Path(folder) / 'constants')
            subprocess.run([compiler, '-x', 'c', '-', '-o', executable], input='\n'.join(lines),
                           text=True, check=True, capture_output=True, timeout=15)
            output = subprocess.check_output([executable], text=True, timeout=3)
        resolved = {}
        for line in output.splitlines():
            prefix, action, constant, number = line.split()
            fn = controls.sdl().SDL_GetScancodeName if prefix == 'key' else controls.sdl().SDL_GetGamepadStringForButton
            resolved[prefix, action, constant] = fn(int(number)).decode()
        actual = {'key': {key: [] for key in controls.KEY_DEFAULTS},
                  'pad': {key: [] for key in controls.PAD_DEFAULTS}}
        for prefix, action, constant in rows:
            if constant == 'PAD_LEFT_TRIGGER':
                value = 'lefttrigger'
            elif constant == 'PAD_RIGHT_TRIGGER':
                value = 'righttrigger'
            else:
                value = resolved[prefix, action, constant]
            actual[prefix][action].append(value)
        for prefix in ('key', 'pad'):
            self.assertEqual({k: ','.join(v) for k, v in actual[prefix].items()}, controls.defaults(prefix))
