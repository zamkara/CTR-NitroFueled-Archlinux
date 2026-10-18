"""Explicit update checks for the native package; no background polling or telemetry."""
import json
from pathlib import Path
import re
import subprocess
import urllib.request

REPOSITORY = 'zamkara/CTR-NitroFueled'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'


def installed_info(root):
    info = json.loads((Path(root) / 'build-info.json').read_text())
    if not re.fullmatch(r'[a-f0-9]{40}', info.get('commit', '')) or not info.get('package_version'):
        raise ValueError('Installed build metadata is invalid')
    return info


def release_info(data):
    tag = data.get('tag_name', '')
    if data.get('draft') or data.get('prerelease') or not re.fullmatch(r'arch-[a-f0-9]{40}', tag):
        raise ValueError('No stable native release is available')
    assets = data.get('assets', [])
    packages = [a for a in assets if re.fullmatch(r'ctr-nitrofueled-[A-Za-z0-9.+_~\-]+-x86_64\.pkg\.tar\.zst', a.get('name', ''))]
    if len(packages) != 1:
        raise ValueError('Release does not contain exactly one native package')
    required = [packages[0]]
    for name in ('install.sh', 'SHA256SUMS'):
        matches = [a for a in assets if a.get('name') == name]
        if len(matches) != 1:
            raise ValueError('Release is incomplete')
        required.extend(matches)
    for asset in required:
        expected = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{asset['name']}"
        if asset.get('browser_download_url') != expected:
            raise ValueError('Unexpected release asset location')
    name = packages[0]['name']
    version = name[len('ctr-nitrofueled-'):-len('-x86_64.pkg.tar.zst')]
    return {'version': version, 'commit': tag[5:], 'url': f'https://github.com/{REPOSITORY}/releases/tag/{tag}'}


def check(root):
    installed = installed_info(root)
    request = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json',
                                                 'User-Agent': 'CTR-NitroFueled-native-update'})
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('Release response is too large')
    available = release_info(json.loads(raw))
    comparison = subprocess.run(['vercmp', installed['package_version'], available['version']],
                                capture_output=True, text=True, check=True, timeout=3)
    return {**available, 'installed': installed['package_version'],
            'update_available': int(comparison.stdout.strip()) < 0}


def installer_command(root):
    installer = Path(root) / 'install.sh'
    if not installer.is_file():
        raise FileNotFoundError('Native installer is unavailable in this build')
    return ['xdg-terminal-exec', '--', '/usr/bin/bash', str(installer)]
