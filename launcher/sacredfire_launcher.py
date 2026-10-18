#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""SacredFire launcher (GTK4 / libadwaita): runs Crash Team Racing: Nitro-Fueled natively on Linux.

Picks the game folder (the merged 1.21 dump), the controller and the start-up options passed to
run.sh as environment variables, edits the port's settings in bbport.ini (game patches, FPS
counter), starts and stops the game and shows its output. Launcher settings live in
~/.config/sacredfire-launcher/settings.json. `--play` starts the game with the saved settings
without a window (Steam Deck game mode).

Derived from bbport's launcher (removed with the Bloodborne profile on 2026-10-09); this one
knows only the CTR profile.
"""

import json
import os
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path

from bbport_i18n import language, set_language, tr

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

PORT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PORT_DIR / "scripts"))
import game_check  # noqa: E402
import steam_shortcuts  # noqa: E402
import control_bindings
import native_update
import library
from library_ui import LibraryMixin

PACKAGED = bool(os.environ.get("BB_PREBUILT"))


def port_version():
    """The build's source revision: VERSION in the package, out/VERSION in a checkout (build.sh
    writes it: the nearest v* tag or the commit, "-dirty" with uncommitted changes)."""
    for name in ("VERSION", "out/VERSION"):
        try:
            return (PORT_DIR / name).read_text().strip()
        except OSError:
            continue
    return ""


DATA_DIR = Path(os.environ.get("BB_DATA_DIR", PORT_DIR))
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "sacredfire-launcher"
CONFIG_FILE = CONFIG_DIR / "settings.json"
MAX_LOG_LINES = 5000
TITLE = "SacredFire"
GAME = "Crash Team Racing: Nitro-Fueled"

# Choices: (label, value); the first is the default.
UI_LANGUAGES = [("System", ""), ("English", "en"), ("Русский", "ru"), ("Português (Brasil)", "pt_BR")]
# The languages CUSA13795 (the Americas build) has, as PS4 system language codes.
LANGUAGES = [("English", "1"), ("Spanish (Latin America)", "20"), ("French", "2"),
             ("Portuguese (Brazil)", "17")]
PRESENT_MODES = [("Mailbox", "Mailbox"), ("FIFO (VSync)", "Fifo"),
                 ("FIFO Relaxed", "FifoRelaxed"), ("Immediate", "Immediate")]
# Game patches (patches/CrashTeamRacing.xml, scripts/patches.py; community patches by illusion and
# TroyWarez from https://github.com/illusionyy/PS-Game-Patch): bbport.ini key,
# label, note. The in-game menu edits the same keys.
PATCHES = [
    ("patch_60fps", "60 FPS unlock", "Requires restart"),
    ("patch_no_motion_blur", "Disable motion blur", "By illusion"),
    ("patch_pro_1080p", "1080p in PS4 Pro mode", "By TroyWarez; only with PS4 Pro mode below"),
]

DEFAULTS = {
    "ui_language": "",
    "game_dir": "" if PACKAGED else str(PORT_DIR / "orig" / "CUSA13795"),
    "user_dir": "",
    "language": "1",
    "fullscreen": False,
    "present_mode": "Mailbox",
    "gamepad": "",
    "gamepad_name": "",
    "neo": False,
    "clear_shader_cache": False,
    "frame_stats": False,
    "save_log": False,
    "mangohud": False,
    "stats_interval": "1000",
    "display": "",
    "dlc_enabled": True,
    "dlc_disabled": [],
    "vk_validation": False,
    "extra_env": "",
}
INI_DEFAULTS = {"show_fps": "0", "fps_limit": "60", "render_res": "1080",
                "temporal": "fsr1", "async_pipelines": "0", "fsr3_sharpness": "0.3",
                "sharpness": "0.7", **{key: "0" for key, _, _ in PATCHES}}


def load_settings():
    settings = dict(DEFAULTS)
    try:
        settings.update(json.loads(CONFIG_FILE.read_text()))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False))


def ini_path():
    return Path(os.environ.get("BB_CONFIG", DATA_DIR / "bbport.ini"))


def load_ini():
    values = dict(INI_DEFAULTS)
    lines = []
    try:
        lines = ini_path().read_text().splitlines()
    except OSError:
        pass
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values, lines


def save_ini(values, lines):
    """Rewrites the edited keys in place, appends missing ones, keeps every other line."""
    written = set()
    out = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in values:
                out.append(f"{key}={values[key]}")
                written.add(key)
                continue
        out.append(line)
    if not lines:
        out.append("# SacredFire / bbport settings (in-game menu: Insert / L3+R3)")
    for key, value in values.items():
        if key not in written:
            out.append(f"{key}={value}")
    ini_path().write_text("\n".join(out) + "\n")


def game_environment(s):
    """Environment for run.sh from the launcher settings."""
    env = dict(os.environ)
    env["BB_GAME_DIR"] = str(Path(s["game_dir"]).expanduser())
    if s["user_dir"]:
        env["BB_USER_DIR"] = s["user_dir"]
    env["BB_LANGUAGE"] = s["language"]
    if s.get("display"):
        env["BB_DISPLAY"] = s["display"]
    env["BB_DLC"] = "1" if s.get("dlc_enabled", True) else "0"
    env["BB_DLC_DISABLED"] = ",".join(s.get("dlc_disabled", []))
    env["BB_MENU_LANGUAGE"] = language()
    values, _ = load_ini()
    env["BB_FULLSCREEN"] = values.get("fullscreen", "1" if s["fullscreen"] else "0")
    env["BB_PRESENT_MODE"] = s["present_mode"]
    if s.get("gamepad"):
        env["BB_GAMEPAD"] = s["gamepad"]
    env["BB_NEO"] = "1" if s.get("neo") else "0"
    if s.get("clear_shader_cache"):
        env["BB_CLEAR_SHADER_CACHE"] = "1"
    if s["frame_stats"]:
        env["BB_FRAME_STATS"] = "1"
    if s.get("save_log"):
        env["BB_SAVE_LOG"] = "1"
    if s["mangohud"]:
        env["MANGOHUD"] = "1"
        interval = s.get("stats_interval", "1000")
        if interval not in ("1000", "2000"):
            interval = "1000"
        env.setdefault("MANGOHUD_CONFIG",
                       "fps,frametime,frame_timing,cpu_stats,gpu_stats,vram,ram,resolution,"
                       f"fps_sampling_period={interval}")
    if s["vk_validation"]:
        env["BB_VK_VALIDATION"] = "1"
    for item in s["extra_env"].split():
        if "=" in item:
            key, value = item.split("=", 1)
            env[key] = value
    return env


def connected_gamepads():
    """(GUID, name) of the connected gamepads (bb-gpu-capabilities --gamepads), [] if unknown."""
    tool = Path(os.environ["BB_PROBE"]).parent / "bb-gpu-capabilities" if os.environ.get("BB_PROBE") else PORT_DIR / ("bin" if PACKAGED else "out") / "bb-gpu-capabilities"
    try:
        run = subprocess.run([str(tool), "--gamepads"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return [tuple(line.split("\t", 1)) for line in run.stdout.splitlines() if "\t" in line]


def connected_displays():
    tool = Path(os.environ["BB_PROBE"]).parent / "bb-gpu-capabilities" if os.environ.get("BB_PROBE") else PORT_DIR / ("bin" if PACKAGED else "out") / "bb-gpu-capabilities"
    try:
        run = subprocess.run([str(tool), "--displays"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return [(parts[0], parts[1]) for line in run.stdout.splitlines()
            if len(parts := line.split("\t")) >= 2]


def flat_button(icon, tooltip, handler):
    button = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, tooltip_text=tooltip)
    button.add_css_class("flat")
    button.connect("clicked", handler)
    return button


def open_folder(window, path):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(window, None, None)


def combo_row(title, subtitle, choices, current):
    model = Gtk.StringList.new([tr(choice[0]) for choice in choices])
    row = Adw.ComboRow(title=title, subtitle=subtitle or "", model=model)
    values = [choice[1] for choice in choices]
    row.set_selected(values.index(current) if current in values else 0)
    row.values = values
    return row


def combo_value(row):
    return row.values[row.get_selected()]


APP_ID = "io.github.sacredfire.Launcher"
# The game's log names this when the known clobbered-dword bug shows itself (gpu/shim/
# bbport_clobber.cpp AskForReport); the log page then asks for the log to be attached to the issue.
ISSUE2_MARKER = "SacredFire issue #2"
ISSUE2_URL = "https://github.com/T3CHNOLOG1C/SacredFire/issues/2"


def install_game_icon(game_dir):
    """The game's own icon (sce_sys/icon0.png) as this app's icon: copied into the user's icon
    theme under the application id, where GTK and the desktop find it (launcher/install-desktop.sh
    does the same for the menu entry). Game files never enter the repository."""
    try:
        source = Path(game_dir).expanduser() / "sce_sys/icon0.png"
        if not source.is_file():
            return False
        share = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        target = share / "icons/hicolor/512x512/apps" / f"{APP_ID}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            target.write_bytes(source.read_bytes())
        return True
    except OSError:
        return False


class LauncherWindow(LibraryMixin, Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=f"{TITLE} {port_version()}".rstrip())
        if install_game_icon(self.settings["game_dir"] if hasattr(self, "settings") else load_settings()["game_dir"]):
            self.set_icon_name(APP_ID)
        self.set_default_size(720, 760)
        self.settings = load_settings()
        set_language(self.settings.get("ui_language", ""))
        self.ini, self.ini_lines = load_ini()
        if "fullscreen" in self.ini:
            self.settings["fullscreen"] = self.ini["fullscreen"] == "1"
        self.process = None
        self.library_busy = False
        self.closing = False
        self.syncing_settings = False
        self.stream = None
        self.build()
        self.connect("close-request", self.on_close)

    def build(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        self.launch_button = Gtk.Button()
        self.launch_button.connect("clicked", self.on_launch)
        header.pack_end(self.launch_button)
        toolbar.add_top_bar(header)
        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(self.stack)
        toolbar.set_content(self.toasts)
        self.set_content(toolbar)
        self.stack.add_titled_with_icon(self.build_settings_page(), "settings", tr("Settings"),
                                        "preferences-system-symbolic")
        self.stack.add_titled_with_icon(self.build_controls_page(), "controls", tr("Controls"),
                                        "input-gaming-symbolic")
        self.stack.add_titled_with_icon(self.build_library_page(), "library", "Library", "folder-symbolic")
        self.stack.add_titled_with_icon(self.build_log_page(), "log", tr("Log"),
                                        "utilities-terminal-symbolic")
        self.update_launch_button()
        self.update_game_status()

    def update_launch_button(self):
        running = self.process is not None
        self.launch_button.set_label(tr("Stop") if running else tr("Play"))
        self.launch_button.remove_css_class("destructive-action" if not running else "suggested-action")
        self.launch_button.add_css_class("destructive-action" if running else "suggested-action")

    # --- settings page -------------------------------------------------------------------

    def build_settings_page(self):
        page = Adw.PreferencesPage()

        game = Adw.PreferencesGroup(title=tr("Game"),
                                    description="Select a prepared 1.21 game folder, or use Library → Prepare Game.")
        self.game_row = Adw.ActionRow(title=tr("Game folder"))
        self.game_status = Gtk.Image(valign=Gtk.Align.CENTER)
        self.game_row.add_suffix(self.game_status)
        self.game_row.add_suffix(flat_button("folder-open-symbolic", tr("Choose the folder with eboot.bin"), self.on_choose_game))
        game.add(self.game_row)
        self.user_row = Adw.ActionRow(title=tr("Saves folder"))
        self.user_row.add_suffix(flat_button("folder-open-symbolic", tr("Choose the saves folder"), self.on_choose_user))
        self.user_row.add_suffix(flat_button("edit-undo-symbolic", tr("Back to the default folder"), self.on_reset_user))
        self.user_row.add_suffix(flat_button("folder-symbolic", tr("Open in the file manager"),
                                             lambda _b: open_folder(self, self.user_dir())))
        game.add(self.user_row)
        self.language_row = combo_row(tr("Game language"), None, LANGUAGES, self.settings["language"])
        game.add(self.language_row)
        page.add(game)

        controls = Adw.PreferencesGroup(title=tr("Controller"),
                                        description="Player assignments and mappings are in Controls.")
        pads = connected_gamepads()
        choices = [(tr("First connected"), "")] + [(name, guid) for guid, name in pads]
        if self.settings["gamepad"] and self.settings["gamepad"] not in [g for g, _ in pads]:
            choices.append((tr("{} (not connected)").format(self.settings["gamepad_name"] or self.settings["gamepad"]), self.settings["gamepad"]))
        self.gamepad_row = combo_row(tr("Controller"), None, choices, self.settings["gamepad"])
        controls.add(self.gamepad_row)
        # Controller selection is unified with per-player assignment in Controls.

        patches = Adw.PreferencesGroup(title=tr("Game patches"),
                                       description="Apply on the next launch.")
        self.patch_rows = {}
        for key, label, note in PATCHES:
            row = Adw.SwitchRow(title=tr(label), subtitle=tr(note), active=self.ini.get(key) == "1")
            if key != "patch_pro_1080p":
                patches.add(row)
            self.patch_rows[key] = row
        page.add(patches)

        console = Adw.PreferencesGroup(title=tr("Console"))
        self.neo_row = Adw.SwitchRow(title=tr("PS4 Pro mode"),
                                     subtitle="",
                                     active=self.settings["neo"])
        console.add(self.neo_row)
        # The selected resolution now chooses the console rendering path automatically.

        screen = Adw.PreferencesGroup(title=tr("Display"))
        self.fullscreen_row = Adw.SwitchRow(title=tr("Fullscreen"), active=self.settings["fullscreen"])
        screen.add(self.fullscreen_row)
        displays = connected_displays()
        display_choices = [("Primary monitor", "")] + [(name + " · " + size, name) for name, size in displays]
        if self.settings["display"] and self.settings["display"] not in [v for _, v in display_choices]:
            display_choices.append((self.settings["display"] + " (not connected)", self.settings["display"]))
        self.display_row = combo_row("Monitor", None, display_choices, self.settings["display"])
        screen.add(self.display_row)
        self.render_row = combo_row("Internal resolution", "Applied on the next launch or in-game restart",
            [(f"{n}p", str(n)) for n in (480, 720, 1080, 1440, 1620, 2160)], self.ini["render_res"])
        screen.add(self.render_row)
        self.upscale_row = combo_row("Upscaling", "DLSS is unavailable in the Linux runtime; FSR 3 is experimental",
            [("Off", "off"), ("AMD FSR 1", "fsr1"), ("AMD FSR 3", "fsr3")], self.ini["temporal"])
        screen.add(self.upscale_row)
        self.fsr_row = combo_row("FSR 1 sharpness", None,
            [(str(n / 10), str(n / 10)) for n in range(0, 21)], self.ini["sharpness"])
        screen.add(self.fsr_row)
        self.fsr3_row = combo_row("FSR 3 sharpness", None,
            [(str(n / 10), str(n / 10)) for n in range(0, 11)], self.ini["fsr3_sharpness"])
        screen.add(self.fsr3_row)
        self.limit_row = combo_row("Frame rate limit", "Higher rates require the 60 FPS unlock patch",
            [("Uncapped", "0")] + [(str(n), str(n)) for n in (30, 60, 72, 90, 120, 144, 240)], self.ini["fps_limit"])
        screen.add(self.limit_row)
        self.limit_row.connect("notify::selected", self.on_fps_limit_selected)
        self.patch_rows["patch_60fps"].connect("notify::active", self.on_fps_patch_changed)
        if self.ini.get("patch_60fps") != "1":
            self.limit_row.set_selected(self.limit_row.values.index("30"))
        self.async_row = Adw.SwitchRow(title="Compile shaders in the background",
            subtitle="Experimental: new effects may appear late", active=self.ini["async_pipelines"] == "1")
        screen.add(self.async_row)
        self.present_row = combo_row(tr("Presentation"), None, PRESENT_MODES, self.settings["present_mode"])
        screen.add(self.present_row)
        self.fps_row = Adw.SwitchRow(title=tr("FPS counter in the corner"), active=self.ini.get("show_fps") == "1")
        screen.add(self.fps_row)
        page.add(screen)

        statistics = Adw.PreferencesGroup(title="Performance statistics")
        self.mangohud_row = Adw.SwitchRow(title="Performance overlay",
            subtitle="FPS, frame time, CPU, GPU, video memory, RAM and resolution via MangoHud",
            active=self.settings["mangohud"])
        statistics.add(self.mangohud_row)
        self.stats_interval_row = combo_row("FPS sampling interval", None,
            [("1 second", "1000"), ("2 seconds", "2000")], self.settings["stats_interval"])
        statistics.add(self.stats_interval_row)
        page.add(statistics)

        dev = Adw.ExpanderRow(title="Diagnostics and advanced options")
        self.stats_row = Adw.SwitchRow(title=tr("Frame statistics in the log"), active=self.settings["frame_stats"])
        dev.add_row(self.stats_row)
        self.save_log_row = Adw.SwitchRow(title=tr("Save the log to a file (logs/)"), active=self.settings["save_log"])
        dev.add_row(self.save_log_row)
        self.cache_row = Adw.SwitchRow(title=tr("Clear the shader cache at start"),
                                       subtitle="Use after a driver update or visual glitches",
                                       active=self.settings["clear_shader_cache"])
        dev.add_row(self.cache_row)
        self.validation_row = Adw.SwitchRow(title=tr("Vulkan validation layer (slow)"), active=self.settings["vk_validation"])
        dev.add_row(self.validation_row)
        self.env_row = Adw.EntryRow(title=tr("Extra environment (VAR=value ...)"), text=self.settings["extra_env"])
        dev.add_row(self.env_row)
        self.ui_language_row = combo_row(tr("Launcher language"), tr("Applies after restarting the launcher"),
                                         UI_LANGUAGES, self.settings["ui_language"])
        dev.add_row(self.ui_language_row)
        advanced = Adw.PreferencesGroup()
        advanced.add(dev)
        page.add(advanced)

        steam = Adw.PreferencesGroup(title=tr("Steam"))
        exe, _start, _options = steam_shortcuts.launcher_command()
        steam_row = Adw.ActionRow(title=tr("Add to Steam"),
                                  subtitle="Close Steam before adding.")
        steam_row.set_tooltip_text(exe)
        add_button = Gtk.Button(label=tr("Add"), valign=Gtk.Align.CENTER)
        add_button.connect("clicked", self.on_add_to_steam)
        steam_row.add_suffix(add_button)
        steam.add(steam_row)
        page.add(steam)
        updates = Adw.PreferencesGroup(title=tr("Application updates"))
        try:
            version = native_update.installed_info(PORT_DIR)["package_version"]
        except (OSError, ValueError):
            version = tr("Development checkout")
        self.update_row = Adw.ActionRow(title=tr("Native Arch package"), subtitle=version)
        self.update_button = Gtk.Button(label=tr("Check for Updates"), valign=Gtk.Align.CENTER)
        self.update_button.connect("clicked", self.on_check_updates)
        self.update_row.add_suffix(self.update_button)
        self.install_update_button = Gtk.Button(label=tr("Install Update"), valign=Gtk.Align.CENTER, visible=False)
        self.install_update_button.connect("clicked", self.on_install_update)
        self.update_row.add_suffix(self.install_update_button)
        updates.add(self.update_row)
        page.add(updates)
        self.update_user_status()
        return page

    def on_fps_limit_selected(self, row, _param):
        if self.syncing_settings:
            return
        if combo_value(row) != "30":
            self.patch_rows["patch_60fps"].set_active(True)

    def on_fps_patch_changed(self, row, _param):
        if self.syncing_settings:
            return
        if row.get_active() and hasattr(self, "limit_row") and combo_value(self.limit_row) == "30":
            self.limit_row.set_selected(self.limit_row.values.index("60"))
        if not row.get_active() and hasattr(self, "limit_row"):
            self.limit_row.set_selected(self.limit_row.values.index("30"))

    def library_data(self):
        return DATA_DIR

    def persist_library_settings(self):
        save_settings(self.settings)

    def game_dir(self):
        return Path(self.settings["game_dir"]).expanduser()

    def user_dir(self):
        return Path(self.settings["user_dir"]).expanduser() if self.settings["user_dir"] else DATA_DIR / "user"

    def update_user_status(self):
        self.user_row.set_subtitle(str(self.user_dir()) + ("" if self.settings["user_dir"] else tr(" (default)")))

    def update_game_status(self):
        path = self.game_dir()
        ok = bool(self.settings["game_dir"]) and (path / "eboot.bin").is_file()
        self.game_row.set_subtitle(str(path) if self.settings["game_dir"] else tr("not chosen"))
        problem = game_check.problem(path) if ok else None
        profile = game_check.profile(path) if ok and not problem else None
        if not ok:
            tooltip = tr("No eboot.bin in the folder")
        elif problem:
            tooltip = game_check.explain(*problem)
            self.game_row.set_subtitle("Update 1.21 required — use Library → Prepare Game" if problem[0] in ("missing_update", "wrong_eboot") else "Game files need attention — see the warning tooltip")
        elif profile and profile["name"] != "ctr":
            tooltip = tr("This is {}; this launcher runs Crash Team Racing: Nitro-Fueled").format(profile["game"])
            problem = ("other_title", profile["title"], profile["version"])
            self.game_row.set_subtitle("Update 1.21 required — use Library → Prepare Game" if problem[0] in ("missing_update", "wrong_eboot") else "Game files need attention — see the warning tooltip")
        else:
            tooltip = f"{GAME} {profile['title']}, {profile['version']}"
        self.game_status.set_from_icon_name("object-select-symbolic" if ok and not problem else "dialog-warning-symbolic")
        self.game_status.set_tooltip_text(tooltip)
        self.launch_button.set_sensitive((ok and not problem) or self.process is not None)
        if hasattr(self, "save_list"):
            self.refresh_library()

    def choose_folder(self, title, initial, chosen):
        dialog = Gtk.FileDialog(title=title, modal=True)
        if initial and Path(initial).is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(initial)))

        def done(dialog, result):
            try:
                folder = dialog.select_folder_finish(result)
            except GLib.Error:
                return
            if folder:
                chosen(folder.get_path())
        dialog.select_folder(self, None, done)

    def on_choose_game(self, _button):
        def chosen(path):
            self.settings["game_dir"] = path
            self.update_game_status()
            self.store()
        self.choose_folder(tr("Game folder (with eboot.bin)"), self.game_dir(), chosen)

    def on_choose_user(self, _button):
        def chosen(path):
            self.settings["user_dir"] = path
            self.update_user_status()
            self.store()
        self.choose_folder(tr("Saves folder"), self.user_dir(), chosen)

    def on_reset_user(self, _button):
        self.settings["user_dir"] = ""
        self.update_user_status()
        self.store()

    def store(self):
        s = self.settings
        s["language"] = combo_value(self.language_row)
        s["gamepad"] = combo_value(self.port_rows[1])
        s["gamepad_name"] = self.port_rows[1].get_selected_item().get_string() if s["gamepad"] else ""
        s["neo"] = self.neo_row.get_active()
        s["fullscreen"] = self.fullscreen_row.get_active()
        s["present_mode"] = combo_value(self.present_row)
        s["display"] = combo_value(self.display_row)
        s["mangohud"] = self.mangohud_row.get_active()
        s["stats_interval"] = combo_value(self.stats_interval_row)
        s["frame_stats"] = self.stats_row.get_active()
        s["save_log"] = self.save_log_row.get_active()
        s["clear_shader_cache"] = self.cache_row.get_active()
        s["vk_validation"] = self.validation_row.get_active()
        s["extra_env"] = self.env_row.get_text()
        s["ui_language"] = combo_value(self.ui_language_row)
        save_settings(s)
        self.ini, self.ini_lines = load_ini()
        for key, row in (("render_res", self.render_row), ("temporal", self.upscale_row),
                         ("fps_limit", self.limit_row), ("sharpness", self.fsr_row), ("fsr3_sharpness", self.fsr3_row)):
            self.ini[key] = combo_value(row)
        self.ini["async_pipelines"] = "1" if self.async_row.get_active() else "0"
        self.ini["fullscreen"] = "1" if self.fullscreen_row.get_active() else "0"
        for port, row in getattr(self, "port_rows", {}).items():
            self.ini[f"port.{port}"] = combo_value(row)
        for key, row in self.patch_rows.items():
            self.ini[key] = "1" if row.get_active() else "0"
        self.ini["show_fps"] = "1" if self.fps_row.get_active() else "0"
        save_ini(self.ini, self.ini_lines)
        self.ini, self.ini_lines = load_ini()

    def environment(self):
        return game_environment(self.settings)

    # --- log page and process ------------------------------------------------------------

    def build_log_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # Shown when the game's log reports the known clobbered-dword bug (issue #2): the log
        # holds the diagnostics that can find its writer, so ask for it.
        self.issue_notice = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                                    margin_top=8, margin_bottom=2, margin_start=8, margin_end=8,
                                    visible=False)
        self.issue_notice.add_css_class("card")
        issue_label = Gtk.Label(
            label=tr("The game hit the known \"clobbered command buffer\" bug (issue #2). "
                     "Please export this log and attach it to the issue so the cause can be fixed."),
            wrap=True, xalign=0, hexpand=True, margin_top=6, margin_bottom=6, margin_start=6)
        self.issue_notice.append(issue_label)
        issue_button = Gtk.Button(label=tr("Open issue #2"), valign=Gtk.Align.CENTER, margin_end=6)
        issue_button.connect("clicked", self.on_open_issue)
        self.issue_notice.append(issue_button)
        box.append(self.issue_notice)
        self.log_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                     wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_top_margin(8)
        self.log_view.set_left_margin(8)
        self.log_view.set_right_margin(8)
        self.log_scroller = Gtk.ScrolledWindow(vexpand=True, child=self.log_view)
        box.append(self.log_scroller)
        # bbport 0.5 (PR 78): the log to the clipboard or to a file, for bug reports.
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_top=6,
                      margin_bottom=6, margin_start=8, margin_end=8)
        self.export_log_button = Gtk.Button(label=tr("Export log…"))
        self.export_log_button.connect("clicked", self.on_export_log)
        bar.append(self.export_log_button)
        self.copy_log_button = Gtk.Button(label=tr("Copy"))
        self.copy_log_button.connect("clicked", self.on_copy_log)
        bar.append(self.copy_log_button)
        box.append(bar)
        buffer = self.log_view.get_buffer()
        buffer.connect("changed", self.on_log_changed)
        self.on_log_changed(buffer)
        return box

    def on_log_changed(self, buffer):
        has_text = buffer.get_char_count() > 0
        self.copy_log_button.set_sensitive(has_text)
        self.export_log_button.set_sensitive(has_text)

    def log_text(self):
        buffer = self.log_view.get_buffer()
        return buffer.get_text(*buffer.get_bounds(), False)

    def on_open_issue(self, _button):
        Gio.AppInfo.launch_default_for_uri(ISSUE2_URL, None)

    def note_issue_line(self, line):
        """A line of the game's log: the notice appears at the first mention of the bug."""
        if ISSUE2_MARKER in line and not self.issue_notice.get_visible():
            self.issue_notice.set_visible(True)
            self.toasts.add_toast(Adw.Toast(
                title=tr("Known bug (issue #2) hit: please export the log and attach it to the issue"),
                timeout=10))

    def on_copy_log(self, _button):
        self.get_clipboard().set(self.log_text())
        self.toasts.add_toast(Adw.Toast(title=tr("Log copied to the clipboard")))

    def on_export_log(self, _button):
        text = self.log_text()
        dialog = Gtk.FileDialog(title=tr("Export log"))
        dialog.set_initial_name(f"sacredfire-{time.strftime('%Y%m%d_%H%M%S')}.log")

        def finish(dialog, result):
            try:
                chosen = dialog.save_finish(result)
            except GLib.Error:
                return  # cancelled
            try:
                Path(chosen.get_path()).write_text(text, encoding="utf-8")
                self.toasts.add_toast(Adw.Toast(title=tr("Log saved to {}").format(chosen.get_path())))
            except OSError as error:
                self.toasts.add_toast(Adw.Toast(title=tr("Could not save the log: {}").format(error)))
        dialog.save(self, None, finish)

    # --- Native package updates ----------------------------------------------------------

    def on_check_updates(self, _button):
        self.update_button.set_sensitive(False)
        self.install_update_button.set_visible(False)
        self.update_row.set_subtitle(tr("Checking the latest published package…"))

        def worker():
            try:
                result = native_update.check(PORT_DIR)
                error = None
            except Exception as exc:
                result, error = None, str(exc)
            GLib.idle_add(self.finish_update_check, result, error)

        threading.Thread(target=worker, daemon=True).start()

    def finish_update_check(self, result, error):
        self.update_button.set_sensitive(True)
        if error:
            self.update_row.set_subtitle(tr("Check failed: {}. Try again.").format(error))
        elif result["update_available"]:
            self.update_row.set_subtitle(tr("Installed: {} · Available: {}").format(
                result["installed"], result["version"]))
            self.install_update_button.set_visible(True)
        else:
            self.update_row.set_subtitle(tr("Up to date · {}").format(result["installed"]))
        return False

    def on_install_update(self, _button):
        if self.process is not None:
            self.toasts.add_toast(Adw.Toast(title=tr("Stop the game before updating")))
            return
        try:
            self.store()
            subprocess.Popen(native_update.installer_command(PORT_DIR))
        except (OSError, ValueError) as error:
            self.toasts.add_toast(Adw.Toast(title=tr("Could not start the installer: {}").format(error)))
            return
        self.toasts.add_toast(Adw.Toast(title=tr("Complete the update in the terminal, then restart the launcher"), timeout=8))

    # --- Input mapping -------------------------------------------------------------------

    def build_controls_page(self):
        page = Adw.PreferencesPage()
        ports = Adw.PreferencesGroup(title="Split-screen controllers",
            description="Ports 2–4 activate extra players when assigned controllers connect. Settings apply on the next launch.")
        self.port_rows = {}
        pads = connected_gamepads()
        for port in range(1, 5):
            current = self.ini.get(f"port.{port}", self.settings["gamepad"] if port == 1 else "")
            choices = [("Automatic" if port == 1 else "Not assigned", "")] + [(name, guid) for guid, name in pads]
            if current and current not in [v for _, v in choices]: choices.append((current + " (not connected)", current))
            row = combo_row(f"Player {port}", None, choices, current)
            ports.add(row)
            self.port_rows[port] = row
        page.add(ports)
        self.binding_rows = {}
        for prefix, title, note in (
            ("key", "Keyboard", "Physical key positions. Select up to four keys per action."),
            ("pad", "Controller", "Remap buttons and triggers. Analog sticks keep their native axes."),
        ):
            group = Adw.PreferencesGroup(title=tr(title), description=tr(note) + " " + tr("Changes apply on the next game launch."))
            for action in control_bindings.defaults(prefix):
                label = control_bindings.LABELS.get(action, action.replace("_", " ").title())
                row = Adw.ActionRow(title=tr(label))
                button = Gtk.Button(label=tr("Change"), valign=Gtk.Align.CENTER)
                button.connect("clicked", self.on_edit_binding, prefix, action)
                row.add_suffix(button)
                self.binding_rows[prefix, action] = row
                group.add(row)
            row = Adw.ActionRow(title=tr("Restore default mappings"))
            button = Gtk.Button(label=tr("Reset"), valign=Gtk.Align.CENTER)
            button.connect("clicked", self.on_reset_bindings, prefix)
            row.add_suffix(button)
            group.add(row)
            page.add(group)
        self.refresh_binding_rows()
        return page

    def refresh_binding_rows(self):
        for (prefix, action), row in self.binding_rows.items():
            value = control_bindings.binding(self.ini, prefix, action)
            row.set_subtitle(", ".join(control_bindings.display_name(prefix, name.strip()) for name in value.split(",")) if value else tr("Unbound"))

    def on_edit_binding(self, _button, prefix, action):
        label = control_bindings.LABELS.get(action, action.replace("_", " ").title())
        dialog = Adw.AlertDialog(heading=tr(label), body=tr("Choose up to four bindings. An empty selection leaves the action unbound."))
        group = Adw.PreferencesGroup()
        options = [""] + list(control_bindings.choices(prefix))
        names = [tr("Unbound")] + [control_bindings.display_name(prefix, name) for name in options[1:]]
        current = control_bindings.binding(self.ini, prefix, action).split(",")
        dropdowns = []
        for index in range(4):
            row = Adw.ActionRow(title=tr("Binding {}").format(index + 1))
            drop = Gtk.DropDown(model=Gtk.StringList.new(names), enable_search=True, valign=Gtk.Align.CENTER)
            value = current[index].strip() if index < len(current) else ""
            drop.set_selected(options.index(value) if value in options else 0)
            row.add_suffix(drop)
            group.add(row)
            dropdowns.append(drop)
        dialog.set_extra_child(group)
        dialog.add_response("cancel", tr("Cancel"))
        dialog.add_response("save", tr("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def respond(_dialog, response):
            if response != "save":
                return
            try:
                value = control_bindings.normalized(prefix, [options[drop.get_selected()] for drop in dropdowns])
                values, lines = load_ini()
                values[f"{prefix}.{action}"] = value
                save_ini(values, lines)
                self.ini, self.ini_lines = load_ini()
            except (OSError, ValueError) as error:
                self.toasts.add_toast(Adw.Toast(title=str(error)))
            self.refresh_binding_rows()

        dialog.connect("response", respond)
        dialog.present(self)

    def on_reset_bindings(self, _button, prefix):
        dialog = Adw.AlertDialog(heading=tr("Restore default mappings?"),
                                body=tr("Only this input section will be reset. Other settings are preserved."))
        dialog.add_response("cancel", tr("Cancel"))
        dialog.add_response("reset", tr("Reset"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def respond(_dialog, response):
            if response == "reset":
                values, lines = load_ini()
                values, lines = control_bindings.reset(values, lines, prefix)
                try:
                    save_ini(values, lines)
                    self.ini, self.ini_lines = load_ini()
                except OSError as error:
                    self.toasts.add_toast(Adw.Toast(title=str(error)))
                self.refresh_binding_rows()

        dialog.connect("response", respond)
        dialog.present(self)

    # --- Steam ---------------------------------------------------------------------------

    def on_add_to_steam(self, _button):
        """A non-Steam shortcut that starts the game directly (--play: no launcher window, so
        it works in the Steam Deck's game mode). Steam rewrites shortcuts.vdf when it exits, so
        it has to be closed while the entry is written."""
        if steam_shortcuts.steam_running():
            self.toasts.add_toast(Adw.Toast(title=tr("Close Steam first: it overwrites its shortcuts when it exits"),
                                            timeout=6))
            return
        files = steam_shortcuts.shortcut_files()
        if not files:
            self.toasts.add_toast(Adw.Toast(title=tr("No Steam user folder found (userdata)"), timeout=6))
            return
        exe, start_dir, options = steam_shortcuts.launcher_command()
        entry = steam_shortcuts.make_entry(exe, start_dir, launch_options=options)
        added = replaced = 0
        for path in files:
            try:
                if steam_shortcuts.add_shortcut(path, entry):
                    added += 1
                else:
                    replaced += 1
            except (OSError, ValueError) as error:
                self.toasts.add_toast(Adw.Toast(title=tr("Could not write {}: {}").format(path, error), timeout=8))
                return
        self.toasts.add_toast(Adw.Toast(
            title=tr("Added to Steam as \"{}\" ({} added, {} updated); start Steam to see it").format(
                steam_shortcuts.NAME, added, replaced), timeout=8))

    def append_log(self, text):
        buffer = self.log_view.get_buffer()
        buffer.insert(buffer.get_end_iter(), text)
        extra = buffer.get_line_count() - MAX_LOG_LINES
        if extra > 0:
            buffer.delete(buffer.get_start_iter(), buffer.get_iter_at_line(extra)[1])
        adj = self.log_scroller.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) and False)

    def on_launch(self, _button):
        if self.library_busy:
            return
        if self.process:
            self.stop_game()
            return
        self.store()
        self.log_view.get_buffer().set_text("")
        self.issue_notice.set_visible(False)
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.set_environ([f"{k}={v}" for k, v in self.environment().items()])
        launcher.set_cwd(str(PORT_DIR))
        try:
            self.process = launcher.spawnv(["setsid", "bash", str(PORT_DIR / "run.sh")])
        except GLib.Error as error:
            self.toasts.add_toast(Adw.Toast(title=tr("Could not start: {}").format(error.message)))
            return
        self.stream = Gio.DataInputStream.new(self.process.get_stdout_pipe())
        self.read_line()
        self.process.wait_async(None, self.on_exit)
        self.update_launch_button()
        self.stack.get_child_by_name("settings").set_sensitive(False)
        self.stack.get_child_by_name("controls").set_sensitive(False)
        self.stack.set_visible_child_name("log")

    def read_line(self):
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)

    def on_line(self, stream, result):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            return
        if line is None:
            return
        self.append_log(line + "\n")
        self.note_issue_line(line)
        self.read_line()

    def stop_game(self):
        if not self.process:
            return
        pid = int(self.process.get_identifier())
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            self.process.force_exit()
        GLib.timeout_add_seconds(3, self.kill_if_running, pid)

    def kill_if_running(self, pid):
        if self.process:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        return False

    def on_exit(self, process, result):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        status = process.get_exit_status() if process.get_if_exited() else -1
        self.process = None
        self.stack.get_child_by_name("settings").set_sensitive(True)
        self.stack.get_child_by_name("controls").set_sensitive(True)
        self.update_launch_button()
        self.ini, self.ini_lines = load_ini()
        self.syncing_settings = True
        for key, row in (("render_res", self.render_row), ("temporal", self.upscale_row),
                         ("fps_limit", self.limit_row), ("sharpness", self.fsr_row), ("fsr3_sharpness", self.fsr3_row)):
            value = self.ini.get(key)
            if value in row.values: row.set_selected(row.values.index(value))
        self.async_row.set_active(self.ini.get("async_pipelines") == "1")
        if "fullscreen" in self.ini:
            self.fullscreen_row.set_active(self.ini["fullscreen"] == "1")
            self.settings["fullscreen"] = self.fullscreen_row.get_active()
            save_settings(self.settings)
        self.fps_row.set_active(self.ini.get("show_fps") == "1")
        for key, row in self.patch_rows.items(): row.set_active(self.ini.get(key) == "1")
        for port, row in self.port_rows.items():
            value = self.ini.get(f"port.{port}", "")
            if value not in row.values:
                row.values.append(value)
                row.get_model().append(value + " (not connected)")
            row.set_selected(row.values.index(value))
        self.syncing_settings = False
        self.refresh_binding_rows()
        self.update_game_status()
        self.refresh_library()
        self.append_log(tr("\n— the game exited (code {}) —\n").format(status))
        if self.closing:
            GLib.idle_add(self.close)

    def on_close(self, _window):
        if self.library_busy:
            self.library_error("Wait for the current file operation before closing")
            return True
        if self.process:
            self.closing = True
            self.stop_game()
            return True
        self.store()
        return False


class LauncherApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        window = self.get_active_window() or LauncherWindow(self)
        window.present()


def play():
    """--play: the game with the saved settings, no window (Steam Deck game mode)."""
    settings = load_settings()
    if not (Path(settings["game_dir"]).expanduser() / "eboot.bin").is_file():
        print("No prepared game selected; opening the launcher for setup.", file=sys.stderr)
        return LauncherApp().run([])
    os.chdir(PORT_DIR)
    os.execvpe("bash", ["bash", str(PORT_DIR / "run.sh")], game_environment(settings))


if __name__ == "__main__":
    if "--play" in sys.argv[1:]:
        sys.exit(play())
    sys.exit(LauncherApp().run([a for a in sys.argv if a != "--play"]))
