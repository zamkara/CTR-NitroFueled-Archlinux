# SPDX-License-Identifier: GPL-2.0-or-later
"""GTK library pages using the launcher's existing Adwaita components."""
import json
import os
from pathlib import Path
import threading
import uuid
from gi.repository import Adw, Gio, GLib, Gtk
import library
import game_check
import patches


class LibraryMixin:
    def action(self, group, title, label, callback, subtitle=''):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        button.connect('clicked', callback)
        row.add_suffix(button)
        group.add(row)
        return row

    def build_library_page(self):
        page = Adw.PreferencesPage()
        setup = Adw.PreferencesGroup(title='Game setup', description='Original base and update dumps remain unchanged. A new merged folder is created for each preparation.')
        self.action(setup, 'Base game and 1.21 update', 'Prepare Game', self.on_prepare_game)
        page.add(setup)
        self.library_status = Adw.ActionRow(title='Ready', subtitle='Select a prepared game to manage its library.')
        self.library_spinner = Gtk.Spinner()
        self.library_status.add_suffix(self.library_spinner)
        self.library_retry = Gtk.Button(label='Retry', valign=Gtk.Align.CENTER, visible=False)
        self.library_retry.connect('clicked', lambda _b: self.library_retry_action())
        self.library_status.add_suffix(self.library_retry)
        state = Adw.PreferencesGroup()
        state.add(self.library_status)
        page.add(state)
        saves = Adw.PreferencesGroup(title='Saves', description='Imports and restores create a backup before changing existing saves. Stop the game first.')
        self.save_player = Gtk.StringList.new(['Player 1', 'Player 2', 'Player 3', 'Player 4'])
        self.save_player_row = Adw.ComboRow(title='Player', model=self.save_player)
        self.save_player_row.connect('notify::selected', lambda *_: self.refresh_library())
        saves.add(self.save_player_row)
        self.action(saves, 'Save slots and backups', 'Refresh', lambda _b: self.refresh_library())
        self.action(saves, 'Back up current saves', 'Back Up', self.on_backup_saves)
        self.action(saves, 'Restore a backup', 'Restore', self.on_restore_saves)
        self.action(saves, 'Export current saves', 'Export', self.on_export_saves)
        self.action(saves, 'Import runtime or decrypted PS4 saves', 'Import', self.on_import_saves)
        self.save_list = Adw.PreferencesGroup(title='Save slots')
        self.save_list_rows = []
        page.add(saves)
        page.add(self.save_list)
        dlc = Adw.PreferencesGroup(title='Downloadable content', description='Only matching entitlement packages from your own dumps are accepted.')
        self.dlc_switch = Adw.SwitchRow(title='Enable DLC', active=self.settings['dlc_enabled'])
        self.dlc_switch.connect('notify::active', self.on_dlc_enabled)
        dlc.add(self.dlc_switch)
        self.action(dlc, 'Add a matching DLC package', 'Add', self.on_add_dlc)
        page.add(dlc)
        self.dlc_list = Adw.PreferencesGroup(title='Installed DLC')
        self.dlc_list_rows = []
        page.add(self.dlc_list)
        self.extra_patches = Adw.PreferencesGroup(title='Additional XML patches',
            description='Bundled community patches are in Settings. Copy additional XML files into your data patches folder, then refresh. Missing or ambiguous signatures are skipped at launch.')
        self.action(self.extra_patches, 'Reload patch files', 'Refresh', lambda _b: self.refresh_library())
        self.extra_patch_rows = []
        page.add(self.extra_patches)
        # Refresh after the window has completed building all controls.
        GLib.idle_add(self.refresh_library)
        return page

    def library_context(self):
        DATA_DIR = self.library_data()
        info = game_check.sfo_info(self.game_dir())
        title = info.get('TITLE_ID')
        if title not in game_check.BY_TITLE:
            raise ValueError('Select a supported prepared game first')
        player = str(self.save_player_row.get_selected() + 1)
        return title, library.save_root(self.user_dir(), title, player), DATA_DIR / 'backups' / title / player

    def library_task(self, title, operation, completed=None):
        if self.library_busy or self.process:
            self.library_status.set_title('Stop the game and wait for the current operation first')
            return
        self.library_busy = True
        self.library_spinner.start()
        self.library_status.set_title(title)
        self.library_status.set_subtitle('Working…')
        self.library_retry.set_visible(False)
        self.launch_button.set_sensitive(False)
        # Freeze settings while operations use their current game/user directories.
        self.stack.get_child_by_name('settings').set_sensitive(False)
        def finish(value=None, error=None):
            self.library_busy = False
            self.library_spinner.stop()
            self.stack.get_child_by_name('settings').set_sensitive(True)
            self.library_status.set_title('Operation failed' if error else 'Completed')
            self.library_status.set_subtitle(str(error or value or title))
            self.library_retry_action = lambda: self.library_task(title, operation, completed)
            self.library_retry.set_visible(error is not None)
            if not error and completed:
                completed(value)
            self.update_game_status()
            self.refresh_library()
            self.library_status.set_title('Operation failed' if error else 'Completed')
            self.library_status.set_subtitle(str(error or value or title))
            self.library_retry_action = lambda: self.library_task(title, operation, completed)
            self.library_retry.set_visible(error is not None)
            return False
        def worker():
            try: result = operation()
            except Exception as error: GLib.idle_add(finish, None, error)
            else: GLib.idle_add(finish, result, None)
        threading.Thread(target=worker, daemon=True).start()

    def library_error(self, error):
        self.library_status.set_title('Cannot continue')
        self.library_status.set_subtitle(str(error))
        self.library_retry_action = self.refresh_library
        self.library_retry.set_visible(True)

    def on_prepare_game(self, _button):
        DATA_DIR = self.library_data()
        if self.process or self.library_busy:
            self.library_error('Stop the game and wait for the current operation first')
            return
        def base_chosen(base):
            def update_chosen(update):
                def done(folder):
                    self.settings['game_dir'] = str(folder)
                    self.store()
                    self.update_game_status()
                self.library_task('Preparing game', lambda: library.prepare_game(base, update, DATA_DIR), done)
            self.choose_folder('Choose the matching 1.21 update', '', update_chosen)
        self.choose_folder('Choose the original base game', '', base_chosen)

    def on_backup_saves(self, _button):
        try: _, root, backups = self.library_context()
        except ValueError as error: return self.library_error(error)
        self.library_task('Backing up saves', lambda: library.backup(root, backups))

    def on_export_saves(self, _button):
        try: _, root, _ = self.library_context()
        except ValueError as error: return self.library_error(error)
        self.choose_folder('Choose export destination', '', lambda folder: self.library_task(
            'Exporting saves', lambda: library.copy_new(root, Path(folder) / ('CTR-saves-' + uuid.uuid4().hex[:8]))))

    def confirm_save_change(self, callback):
        dialog = Adw.AlertDialog(heading='Replace existing saves?', body='Current saves will be backed up first. The game must be stopped.')
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('continue', 'Continue')
        dialog.set_response_appearance('continue', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', lambda _d, response: callback() if response == 'continue' else None)
        dialog.present(self)

    def on_restore_saves(self, _button):
        try: _, root, backups = self.library_context()
        except ValueError as error: return self.library_error(error)
        def chosen(folder):
            self.confirm_save_change(lambda: self.library_task('Restoring saves',
                lambda: library.install_saves(folder, root, backups, replace=True, title=root.name)))
        self.choose_folder('Choose a save backup', backups, chosen)

    def on_import_saves(self, _button):
        try: title, root, backups = self.library_context()
        except ValueError as error: return self.library_error(error)
        def chosen(folder):
            self.confirm_save_change(lambda: self.library_task('Importing saves',
                lambda: library.import_saves(folder, root, backups, title)))
        self.choose_folder('Choose runtime saves or a decrypted PS4 save', '', chosen)

    def dlc_dir(self):
        DATA_DIR = self.library_data()
        return Path(os.environ.get('BB_DLC_DIR', DATA_DIR / 'dlc'))

    def on_dlc_enabled(self, row, _param):
        self.settings['dlc_enabled'] = row.get_active()
        self.persist_library_settings()

    def on_add_dlc(self, _button):
        try: title, _, _ = self.library_context()
        except ValueError as error: return self.library_error(error)
        dialog = Gtk.FileDialog(title='Choose a matching DLC package', modal=True)
        f = Gtk.FileFilter(name='PS4 DLC packages')
        f.add_pattern('*.pkg')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)
        def selected(dialog, result):
            try: file = dialog.open_finish(result)
            except GLib.Error: return
            if file and file.get_path():
                self.library_task('Adding DLC', lambda: library.add_dlc(file.get_path(), self.dlc_dir(), title))
        dialog.open(self, None, selected)

    def on_remove_dlc(self, _button, source, title):
        dialog = Adw.AlertDialog(heading='Remove DLC package?',
            body='This removes only the package in the managed DLC folder. A separately imported original is preserved.')
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('remove', 'Remove')
        dialog.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', lambda _d, response: self.library_task('Removing DLC',
            lambda: library.remove_dlc(source, self.dlc_dir(), title)) if response == 'remove' else None)
        dialog.present(self)

    def toggle_dlc(self, row, _param, label):
        disabled = set(self.settings.get('dlc_disabled', []))
        if row.get_active(): disabled.discard(label)
        else: disabled.add(label)
        self.settings['dlc_disabled'] = sorted(disabled)
        self.persist_library_settings()

    def toggle_patch(self, row, _param, key, path):
        try:
            config = json.loads(path.read_text()) if path.exists() else {}
            for field in ('enabled', 'disabled'):
                values = set(config.get(field, []))
                values.discard(key)
                if (field == 'enabled') == row.get_active(): values.add(key)
                config[field] = sorted(values)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name('.patches-' + uuid.uuid4().hex)
            temp.write_text(json.dumps(config, indent=2) + '\n')
            temp.replace(path)
        except (OSError, ValueError) as error: self.library_error(error)

    def refresh_library(self):
        if not hasattr(self, 'save_list') or self.library_busy:
            return False
        DATA_DIR = self.library_data()
        for group, attr in ((self.save_list, 'save_list_rows'), (self.dlc_list, 'dlc_list_rows'), (self.extra_patches, 'extra_patch_rows')):
            for row in getattr(self, attr): group.remove(row)
            setattr(self, attr, [])
        try:
            title, root, _ = self.library_context()
            slots = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.endswith(('.sce_sys','.memory'))) if root.exists() else []
            for slot in slots:
                meta = root / (slot.name + '.sce_sys') / 'param.bin'
                details = ''
                if meta.is_file():
                    with meta.open('rb') as file: blob = file.read(256)
                    details = ' · '.join(v.split(b'\0',1)[0].decode('utf-8', 'replace') for v in (blob[:128], blob[128:256])).strip(' ·')
                row = Adw.ActionRow(title=slot.name, subtitle=details or str(slot))
                self.save_list.add(row)
                self.save_list_rows.append(row)
            if not slots:
                row = Adw.ActionRow(title='No saves yet', subtitle='Play the game or use Import above.')
                self.save_list.add(row)
                self.save_list_rows.append(row)
            addons = library.content_profile.find_addons(self.dlc_dir(), title)
            for label, name, source in addons:
                row = Adw.SwitchRow(title=name, subtitle=label, active=label not in self.settings.get('dlc_disabled', []))
                row.connect('notify::active', self.toggle_dlc, label)
                source_path = self.dlc_dir() / source
                if source_path.is_file() and source_path.suffix.lower() == '.pkg':
                    remove = Gtk.Button(icon_name='user-trash-symbolic', tooltip_text='Remove managed DLC package', valign=Gtk.Align.CENTER)
                    remove.connect('clicked', self.on_remove_dlc, source_path, title)
                    row.add_suffix(remove)
                self.dlc_list.add(row)
                self.dlc_list_rows.append(row)
            if not addons:
                row = Adw.ActionRow(title='No matching DLC', subtitle='Use Add above to import your own package.')
                self.dlc_list.add(row)
                self.dlc_list_rows.append(row)
            config_path = Path(os.environ.get('BB_PATCHES_CONFIG', DATA_DIR / 'patches.json'))
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
            directory = Path(os.environ.get('BB_PATCHES_DIR', DATA_DIR / 'patches'))
            catalogs = patches.available_patches(directory, '01.21', title)
            seen = set(patches.GAME_PATCH_KEYS.values())
            for key, file, meta in catalogs:
                if key in seen: continue
                seen.add(key)
                active = key in config.get('enabled', []) or (key not in config.get('disabled', []) and meta.get('isEnabled', 'false').lower() == 'true')
                row = Adw.SwitchRow(title=meta.get('Name', key), subtitle=file.name, active=active)
                row.connect('notify::active', self.toggle_patch, key, config_path)
                self.extra_patches.add(row)
                self.extra_patch_rows.append(row)
            if not self.extra_patch_rows:
                row = Adw.ActionRow(title='No additional patches', subtitle=str(directory))
                self.extra_patches.add(row)
                self.extra_patch_rows.append(row)
        except (OSError, ValueError) as error:
            self.library_error(error)
        return False
