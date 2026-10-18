# SPDX-License-Identifier: GPL-2.0-or-later
"""Local game library operations. Never modify the original dumps or imported saves."""
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import game_check
import content_profile
from prepare import sfo


def safe_name(value):
    if not value or value in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]{1,31}', value):
        raise ValueError('Invalid save slot name')
    return value


def checked_tree(folder):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Select a regular directory')
    for root, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            p = Path(root) / name
            if p.is_symlink() or not (p.is_dir() or p.is_file()):
                raise ValueError('Symbolic links and special files are not accepted in saves')
    return folder


def copy_new(source, target):
    source = checked_tree(source)
    target = Path(target)
    if target.resolve().is_relative_to(source.resolve()):
        raise ValueError('Destination must be outside the source directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.copy-', dir=target.parent))
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True)
        if source.name in game_check.BY_TITLE:
            (stage / '.ctr-save.json').write_text(json.dumps({'title': source.name}) + '\n')
        if target.exists():
            raise ValueError('Destination already exists')
        stage.rename(target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


def prepare_game(base, update, data):
    # Reuse the upstream merge tool, but always publish to a new directory.
    sys.path.insert(0, str(ROOT / 'tools'))
    from merge_update import layout
    base, update, data = map(Path, (base, update, data))
    def info(folder):
        trees = layout(folder)
        if not trees:
            raise ValueError('The selected dump has no executable and metadata')
        for root, prefix in trees:
            path = root / 'param.sfo' if str(prefix) == 'sce_sys' else root / 'sce_sys/param.sfo'
            if path.is_file():
                return sfo(path.read_bytes()), root
        raise ValueError('Game metadata is missing')
    b, _ = info(base)
    u, executable_root = info(update)
    if b.get('TITLE_ID') != u.get('TITLE_ID') or b.get('TITLE_ID') not in game_check.BY_TITLE:
        raise ValueError('Select matching supported base and update editions')
    if b.get('CATEGORY') != 'gd' or u.get('CATEGORY') != 'gp' or u.get('APP_VER') != '01.21':
        raise ValueError('Select a base game and its 1.21 update')
    # Validate executable bytes against update metadata, including split-layout dumps.
    digest = game_check.image_sha256(executable_root)
    expected = game_check.SUPPORTED.get(digest)
    if expected and expected['title'] != u['TITLE_ID']:
        raise ValueError('Update executable and metadata belong to different editions')
    if digest in game_check.OLD_IMAGES or (u['TITLE_ID'] == 'CUSA14876' and digest != game_check.EU_IMAGE):
        raise ValueError('The update executable is not a supported 1.21 build')
    parent = data / 'prepared'
    for source in (base, update):
        if parent.resolve().is_relative_to(source.resolve()):
            raise ValueError('Prepared output must be outside the source dumps')
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / (u['TITLE_ID'] + '-1.21-' + uuid.uuid4().hex[:8])
    try:
        subprocess.run([sys.executable, str(ROOT / 'tools/merge_update.py'), str(base), str(update), str(target)],
                       check=True, capture_output=True, text=True)
        issue = game_check.problem(target)
        if issue:
            raise ValueError(game_check.explain(*issue))
        for module in game_check.BY_TITLE[u['TITLE_ID']]['modules']:
            if not (target / 'sce_module' / module).is_file():
                raise ValueError(f'Required module is missing: {module}')
        return target
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def save_root(user, title, player='1'):
    if title not in game_check.BY_TITLE or not str(player).isdigit():
        raise ValueError('Select a supported game and a valid player')
    return Path(user) / 'savedata' / str(player) / title


def backup(source, backups):
    source = Path(source)
    if not source.is_dir() or not any(source.iterdir()):
        raise ValueError('No saves to back up')
    return copy_new(source, Path(backups) / ('saves-' + time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]))


def validate_runtime_saves(folder):
    folder = checked_tree(folder)
    slots = []
    for item in folder.iterdir():
        if item.is_dir() and not item.name.endswith(('.sce_sys', '.memory')):
            safe_name(item.name)
            meta = folder / (item.name + '.sce_sys') / 'param.bin'
            if not meta.is_file() or meta.stat().st_size != 1328:
                raise ValueError('A save slot is missing its 1328-byte param.bin')
            slots.append(item)
    if not slots:
        raise ValueError('No recognized runtime save slots in this folder')
    return folder


def install_saves(source, destination, backups, replace=False, title=None):
    """Stage a complete replacement; retain a backup and roll back if publication fails."""
    source = validate_runtime_saves(source)
    marker = source / '.ctr-save.json'
    source_title = json.loads(marker.read_text()).get('title') if marker.exists() else (source.name if source.name in game_check.BY_TITLE else None)
    if title and source_title and title != source_title:
        raise ValueError('The save backup belongs to another game edition')
    destination = Path(destination)
    if source.resolve() == destination.resolve() or source.resolve().is_relative_to(destination.resolve()) or destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('Import source and active saves must be separate')
    if destination.is_symlink():
        raise ValueError('Active saves must not be a symbolic link')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.save-stage-', dir=destination.parent) as temp:
        staged = Path(temp) / 'ready'
        if destination.exists() and any(destination.iterdir()):
            backup(destination, backups)  # failure aborts before modifying active saves
            if not replace:
                shutil.copytree(checked_tree(destination), staged)
        staged.mkdir(exist_ok=True)
        for item in source.iterdir():
            target = staged / item.name
            if target.is_dir(): shutil.rmtree(target)
            elif target.exists(): target.unlink()
            if item.is_dir(): shutil.copytree(item, target)
            else: shutil.copy2(item, target)
        previous = Path(temp) / 'previous'
        existed = destination.exists()
        if existed:
            destination.rename(previous)
        try:
            staged.rename(destination)
        except Exception:
            if existed:
                previous.rename(destination)
            raise
    return destination


def import_saves(source, destination, backups, title):
    source = checked_tree(source)
    param = source / 'sce_sys/param.sfo'
    if not param.exists():
        return install_saves(source, destination, backups, title=title)
    info = sfo(param.read_bytes())
    if info.get('TITLE_ID') != title:
        raise ValueError('The decrypted save belongs to another game edition')
    slot = safe_name(info.get('SAVEDATA_DIRECTORY', ''))
    with tempfile.TemporaryDirectory(prefix='ctr-save-import-') as temp:
        root = Path(temp)
        target = root / slot
        target.mkdir()
        for p in source.iterdir():
            if p.name != 'sce_sys':
                if p.is_dir(): shutil.copytree(p, target / p.name)
                else: shutil.copy2(p, target / p.name)
        if not any(target.iterdir()):
            raise ValueError('The decrypted save contains no data files')
        meta = root / (slot + '.sce_sys')
        meta.mkdir()
        def text(key, size):
            return str(info.get(key, '')).encode('utf-8')[:size-1].ljust(size, b'\0')
        blob = text('MAINTITLE',128) + text('SUBTITLE',128) + text('DETAIL',1024)
        blob += struct.pack('<Ii q32s', int(info.get('SAVEDATA_PARAMS',0)) & 0xffffffff, 0, int(time.time()), b'')
        (meta / 'param.bin').write_bytes(blob)
        icon = source / 'sce_sys/icon0.png'
        if icon.is_file(): shutil.copy2(icon, meta / 'icon0.png')
        return install_saves(root, destination, backups, title=title)


def add_dlc(source, directory, title):
    source, directory = Path(source), Path(directory)
    if source.is_symlink() or not source.is_file() or source.suffix.lower() != '.pkg':
        raise ValueError('Select a regular DLC package')
    info = content_profile.pkg_param(source)
    content = info.get('CONTENT_ID','')
    if info.get('CATEGORY') != 'ac' or info.get('TITLE_ID') != title or content[7:16] != title:
        raise ValueError('The package is not a DLC for the selected edition')
    label = content[20:]
    if not re.fullmatch('[A-Za-z0-9_-]{1,16}', label):
        raise ValueError('Invalid DLC entitlement label')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (title + '-' + label + '.pkg')
    if target.exists():
        raise ValueError('This DLC is already installed')
    stage = directory / ('.dlc-' + uuid.uuid4().hex)
    try:
        shutil.copy2(source, stage)
        os.replace(stage, target)
    finally:
        stage.unlink(missing_ok=True)
    return target


def remove_dlc(source, directory, title):
    source, directory = Path(source), Path(directory)
    if source.is_symlink() or source.parent.resolve() != directory.resolve() or not source.is_file():
        raise ValueError('Only regular packages in the managed DLC directory can be removed')
    info = content_profile.pkg_param(source)
    if info.get('CATEGORY') != 'ac' or info.get('TITLE_ID') != title or info.get('CONTENT_ID', '')[7:16] != title:
        raise ValueError('The package is not a matching DLC')
    source.unlink()
    return 'DLC removed from the managed library'
