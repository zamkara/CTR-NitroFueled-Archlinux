"""SDL binding names and the runtime's key.*/pad.* configuration format."""
import ctypes
from functools import lru_cache

KEY_DEFAULTS = {
    'move_up': 'W', 'move_down': 'S', 'move_left': 'A', 'move_right': 'D',
    'cross': 'Space', 'square': 'E', 'circle': 'Left Shift', 'triangle': 'Q',
    'l1': '1', 'r1': '3', 'l2': 'R', 'r2': 'F', 'l3': 'Z', 'r3': 'C',
    'options': 'Return', 'touchpad': 'Tab', 'touchpad_right': 'Backspace',
    'up': 'I', 'down': 'K', 'left': 'J', 'right': 'L',
    'look_up': 'Up', 'look_down': 'Down', 'look_left': 'Left', 'look_right': 'Right',
}
PAD_DEFAULTS = {
    'cross': 'a', 'circle': 'b', 'square': 'x', 'triangle': 'y',
    'l1': 'leftshoulder', 'r1': 'rightshoulder', 'l2': 'lefttrigger', 'r2': 'righttrigger',
    'l3': 'leftstick', 'r3': 'rightstick', 'options': 'start', 'touchpad': 'back,touchpad',
    'touchpad_right': '', 'up': 'dpup', 'down': 'dpdown', 'left': 'dpleft', 'right': 'dpright',
}
LABELS = {
    'move_up': 'Left stick up', 'move_down': 'Left stick down',
    'move_left': 'Left stick left', 'move_right': 'Left stick right',
    'look_up': 'Right stick up', 'look_down': 'Right stick down',
    'look_left': 'Right stick left', 'look_right': 'Right stick right',
    'cross': 'Cross / accelerate', 'square': 'Square / brake', 'options': 'Options / pause',
    'touchpad': 'Touchpad left', 'touchpad_right': 'Touchpad right',
    'up': 'D-pad up', 'down': 'D-pad down', 'left': 'D-pad left', 'right': 'D-pad right',
}


@lru_cache(maxsize=1)
def sdl():
    lib = ctypes.CDLL('libSDL3.so.0')
    for name in ('SDL_GetScancodeName', 'SDL_GetGamepadStringForButton'):
        fn = getattr(lib, name)
        fn.argtypes = [ctypes.c_int]
        fn.restype = ctypes.c_char_p
    return lib


@lru_cache(maxsize=2)
def choices(prefix):
    if prefix == 'key':
        values = [sdl().SDL_GetScancodeName(i) for i in range(512)]
    elif prefix == 'pad':
        values = [sdl().SDL_GetGamepadStringForButton(i) for i in range(32)]
        values += [b'lefttrigger', b'righttrigger']
    else:
        raise ValueError('Unknown binding type')
    return tuple(sorted({v.decode() for v in values if v}, key=str.casefold))


def defaults(prefix):
    return KEY_DEFAULTS if prefix == 'key' else PAD_DEFAULTS


def binding(values, prefix, action):
    return values.get(f'{prefix}.{action}', defaults(prefix)[action])


def normalized(prefix, names):
    names = list(dict.fromkeys(name for name in names if name))
    if len(names) > 4 or any(name not in choices(prefix) for name in names):
        raise ValueError('Select up to four supported bindings')
    return ','.join(names)


def reset(values, lines, prefix):
    keys = {f'{prefix}.{action}' for action in defaults(prefix)}
    return ({k: v for k, v in values.items() if k not in keys},
            [line for line in lines if line.lstrip().startswith('#') or line.split('=', 1)[0].strip() not in keys])


PAD_LABELS = {
    'a': 'A / South', 'b': 'B / East', 'x': 'X / West', 'y': 'Y / North',
    'back': 'Back / Share', 'start': 'Start / Menu', 'guide': 'Guide',
    'leftshoulder': 'Left shoulder', 'rightshoulder': 'Right shoulder',
    'lefttrigger': 'Left trigger', 'righttrigger': 'Right trigger',
    'leftstick': 'Left stick press', 'rightstick': 'Right stick press',
    'dpup': 'D-pad up', 'dpdown': 'D-pad down', 'dpleft': 'D-pad left', 'dpright': 'D-pad right',
    'touchpad': 'Touchpad press',
}


def display_name(prefix, name):
    return PAD_LABELS.get(name, name.replace('_', ' ').title()) if prefix == 'pad' else name
