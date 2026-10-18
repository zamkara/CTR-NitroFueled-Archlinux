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


@lru_cache(maxsize=1)
def physical_keymap():
    """GDK's Linux hardware keycodes use the XKB keycode space on X11 and Wayland."""
    import atexit
    lib = ctypes.CDLL('libxkbcommon.so.0')
    class Names(ctypes.Structure):
        _fields_ = [(name, ctypes.c_char_p) for name in ('rules','model','layout','variant','options')]
    lib.xkb_context_new.argtypes = [ctypes.c_int]
    lib.xkb_context_new.restype = ctypes.c_void_p
    lib.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.POINTER(Names), ctypes.c_int]
    lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
    lib.xkb_keymap_key_get_syms_by_level.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint))]
    lib.xkb_keymap_key_get_syms_by_level.restype = ctypes.c_int
    lib.xkb_keysym_get_name.argtypes = [ctypes.c_uint, ctypes.c_char_p, ctypes.c_size_t]
    lib.xkb_context_unref.argtypes = [ctypes.c_void_p]
    lib.xkb_keymap_unref.argtypes = [ctypes.c_void_p]
    context = lib.xkb_context_new(0)
    if not context: raise OSError('Could not initialize keyboard recording')
    keymap = lib.xkb_keymap_new_from_names(context, ctypes.byref(Names(b'evdev',b'pc105',b'us',b'',b'')),0)
    if not keymap:
        lib.xkb_context_unref(context)
        raise OSError('Could not load the physical keyboard map')
    atexit.register(lambda: (lib.xkb_keymap_unref(keymap), lib.xkb_context_unref(context)))
    return lib, keymap


def physical_key_name(keycode):
    """Canonical SDL physical name for a GDK hardware code; unknown codes remain unbound."""
    lib, keymap = physical_keymap()
    symbols = ctypes.POINTER(ctypes.c_uint)()
    if lib.xkb_keymap_key_get_syms_by_level(keymap, keycode, 0, 0, ctypes.byref(symbols)) != 1:
        return None
    text = ctypes.create_string_buffer(128)
    if lib.xkb_keysym_get_name(symbols[0], text, len(text)) <= 0: return None
    name = text.value.decode()
    aliases = {'Shift_L':'Left Shift','Shift_R':'Right Shift','Control_L':'Left Ctrl','Control_R':'Right Ctrl',
               'Alt_L':'Left Alt','Alt_R':'Right Alt','Super_L':'Left GUI','Super_R':'Right GUI',
               'space':'Space','Prior':'PageUp','Next':'PageDown','Caps_Lock':'CapsLock',
               'Num_Lock':'Numlock','Scroll_Lock':'ScrollLock','Print':'PrintScreen',
               'KP_Enter':'Keypad Enter','KP_Add':'Keypad +','KP_Subtract':'Keypad -',
               'KP_Multiply':'Keypad *','KP_Divide':'Keypad /','KP_Delete':'Keypad .',
               'KP_Insert':'Keypad 0','KP_End':'Keypad 1','KP_Down':'Keypad 2','KP_Next':'Keypad 3',
               'KP_Left':'Keypad 4','KP_Begin':'Keypad 5','KP_Right':'Keypad 6','KP_Home':'Keypad 7',
               'KP_Up':'Keypad 8','KP_Prior':'Keypad 9','semicolon':';','apostrophe':"'",'grave':'`',
               'minus':'-','equal':'=','bracketleft':'[','bracketright':']','backslash':'\\',
               'comma':',','period':'.','slash':'/'}
    name = aliases.get(name, name.upper() if len(name) == 1 else name)
    canonical = {choice.casefold():choice for choice in choices('key')}
    return canonical.get(name.casefold())
