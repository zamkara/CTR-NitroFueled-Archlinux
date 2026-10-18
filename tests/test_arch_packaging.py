"""Native packaging regression tests; installer tests never invoke real pacman/sudo."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import subprocess
import sys
import tempfile
import termios
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class InstallerTests(unittest.TestCase):
    def run_installer(self, installed='', corrupt=False, missing=False):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            binary = work / 'bin'
            binary.mkdir()
            package = 'ctr-nitrofueled-2.0-1-x86_64.pkg.tar.zst'
            (work / package).write_bytes(b'native test package')
            digest = '0' * 64 if corrupt else hashlib.sha256((work / package).read_bytes()).hexdigest()
            (work / 'SHA256SUMS').write_text(f'{digest}  {package}\n')
            assets = [] if missing else [{'name': n, 'browser_download_url':
                f'https://github.com/zamkara/CTR-NitroFueled/releases/download/arch-test/{n}'}
                for n in (package, 'SHA256SUMS')]
            (work / 'release.json').write_text(json.dumps({'assets': assets}))
            (work / 'installed').write_text(installed)
            dispatcher = '''import os,pathlib,shutil,sys
root=pathlib.Path(os.environ['FIXTURE']);args=sys.argv[1:];tool=pathlib.Path(sys.argv[0]).name
if tool=='curl':
    url=next(a for a in args if a.startswith('https://'))
    source='release.json' if url.endswith('/latest') else url.rsplit('/',1)[-1]
    shutil.copyfile(root/source,args[args.index('-o')+1])
elif tool=='pacman':
    if args[0]=='-Qp':print('ctr-nitrofueled 2.0-1')
    elif args[0]=='-Q':
        version=(root/'installed').read_text()
        if not version:sys.exit(1)
        print('ctr-nitrofueled '+version)
    elif args[0]=='-U':(root/'transaction').write_text(' '.join(args))
    else:raise SystemExit('Unexpected pacman arguments: '+repr(args))
elif tool=='vercmp':print((args[0]>args[1])-(args[0]<args[1]))
elif tool=='id':print('0')
elif tool=='sudo':raise SystemExit('Real privilege escalation is forbidden in tests')
'''
            for tool in ('curl', 'pacman', 'vercmp', 'id', 'sudo'):
                path = binary / tool
                path.write_text(f'#!{sys.executable}\n' + dispatcher)
                path.chmod(0o755)
            master, slave = pty.openpty()
            def terminal():
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            try:
                done = subprocess.run(['bash', str(ROOT / 'packaging/arch/install.sh')],
                    stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    preexec_fn=terminal, timeout=15,
                    env={**os.environ, 'PATH': str(binary)+os.pathsep+os.environ['PATH'],
                         'FIXTURE': str(work)})
            finally:
                os.close(master)
                os.close(slave)
            return done, (work / 'transaction').exists()

    def test_first_install_uses_verified_package(self):
        done, installed = self.run_installer()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue(installed)
        self.assertIn(': OK', done.stdout)

    def test_same_command_upgrades_older_installation(self):
        done, installed = self.run_installer(installed='1.0-1')
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue(installed)

    def test_current_and_newer_versions_skip_transaction(self):
        for version in ('2.0-1', '3.0-1'):
            done, installed = self.run_installer(installed=version)
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertFalse(installed)
            self.assertIn('already current', done.stdout)

    def test_corrupt_package_never_reaches_pacman(self):
        done, installed = self.run_installer(corrupt=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(installed)

    def test_incomplete_release_never_reaches_pacman(self):
        done, installed = self.run_installer(missing=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(installed)


class NativeIntegrationTests(unittest.TestCase):
    def test_steam_uses_native_wrapper(self):
        sys.path.insert(0, str(ROOT / 'launcher'))
        import steam_shortcuts
        with patch.dict(os.environ, {'CTR_NATIVE_LAUNCHER': '/usr/bin/ctr-nitrofueled'}):
            self.assertEqual(steam_shortcuts.launcher_command(),
                             ('/usr/bin/ctr-nitrofueled', '/usr/bin', '--play'))

    def test_only_native_release_workflow_is_enabled(self):
        workflows = list((ROOT / '.github/workflows').glob('*.yml'))
        self.assertEqual([p.name for p in workflows], ['archlinux.yml'])
        workflow = workflows[0].read_text()
        self.assertIn('needs: [sync, smoke]', workflow)
        self.assertIn('sha256sum --check SHA256SUMS', workflow)
        self.assertNotIn('windows-2025', workflow)

    def test_source_cache_does_not_collide_with_launcher(self):
        recipe = (ROOT / 'packaging/arch/PKGBUILD').read_text()
        self.assertIn('ctr-nitrofueled-source::git+', recipe)
        self.assertNotIn('"ctr-nitrofueled::git+', recipe)

    def test_native_wrapper_does_not_write_bytecode_to_system_directory(self):
        wrapper = (ROOT / 'packaging/arch/ctr-nitrofueled').read_text()
        self.assertIn('export PYTHONDONTWRITEBYTECODE=1', wrapper)

    def test_package_installs_runtime_helpers(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'src/ctr-nitrofueled-source'
            source.mkdir(parents=True)
            for name in ('launcher', 'scripts', 'patches', 'packaging/arch', 'gpu/third_party/fonts'):
                shutil.copytree(ROOT / name, source / name, ignore=shutil.ignore_patterns('__pycache__'))
            for name in ('run.sh', 'run.py', 'README.md', 'LICENSE', 'tools/merge_update.py',
                         'tools/gen_import_names.py', 'docs/images/logo.png'):
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            for name in ('out/sacredfire', 'out/bb-gpu-capabilities', 'out/gpu/libbbgpu.so', 'out/VERSION'):
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('synthetic build fixture')
            (root / 'src/vk_mem_alloc.h').write_text('VMA license fixture')
            stage = root / 'pkg'
            subprocess.run(['bash', '-eu', '-c',
                'source "$1"; srcdir=$2; pkgdir=$3; startdir=$4; package', 'package-test',
                str(ROOT / 'packaging/arch/PKGBUILD'), str(root / 'src'), str(stage),
                str(ROOT / 'packaging/arch')], check=True, capture_output=True, text=True)
            app = stage / 'usr/lib/ctr-nitrofueled'
            for name in ('run.sh', 'scripts/prepare.py', 'scripts/link_libc.py',
                         'scripts/link_modules.py', 'scripts/content_profile.py', 'scripts/patches.py',
                         'tools/gen_import_names.py', 'tools/merge_update.py',
                         'launcher/sacredfire_launcher.py', 'launcher/steam_shortcuts.py',
                         'launcher/control_bindings.py', 'launcher/native_update.py', 'install.sh'):
                self.assertTrue((app / name).is_file(), name)
            info = json.loads((app / 'build-info.json').read_text())
            self.assertRegex(info['commit'], r'^[a-f0-9]{40}$')
            self.assertTrue((stage / 'usr/share/licenses/ctr-nitrofueled/fonts-LICENSE-DejaVu.txt').is_file())
            for name in ('ctr-nitrofueled.desktop', 'ctr-nitrofueled-play.desktop'):
                self.assertTrue((stage / 'usr/share/applications' / name).is_file())

    def test_launcher_renderer_default_and_user_override(self):
        for override, expected in ((None, 'cairo'), ('gl', 'gl'), ('vulkan', 'vulkan')):
            with self.subTest(renderer=override), tempfile.TemporaryDirectory() as folder:
                env = {'PATH': os.environ['PATH'], 'HOME': folder,
                       'VK_DRIVER_FILES': '/selected/game-driver.json'}
                if override is not None:
                    env['GSK_RENDERER'] = override
                result = subprocess.run(['bash', '-c',
                    'cd() { :; }; exec() { printf "%s|%s" "$GSK_RENDERER" "$VK_DRIVER_FILES"; }; source "$1"',
                    'wrapper-test', str(ROOT / 'packaging/arch/ctr-nitrofueled')],
                    env=env, capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, expected + '|/selected/game-driver.json')


class UpstreamSyncTests(unittest.TestCase):
    def test_code_updates_keep_fork_policy_and_remove_added_upstream_workflow(self):
        self.exercise(conflict=False)

    def test_conflicting_code_aborts_and_keeps_original_head(self):
        self.exercise(conflict=True)

    def exercise(self, conflict):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);upstream=root/'upstream';fork=root/'fork'
            def git(where,*args,check=True):
                return subprocess.run(['git','-C',str(where),*args],check=check,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            upstream.mkdir();git(upstream,'init','-b','main')
            git(upstream,'config','user.name','Test');git(upstream,'config','user.email','test@example.invalid')
            for name,text in [('README.md','upstream original'),('.github/workflows/old.yml','old'),('packaging/base','original'),('docs/UPSTREAM.md','original'),('tests/test_arch_packaging.py','original'),('src/runtime.c','base')]:
                path=upstream/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text+'\n')
            git(upstream,'add','.');git(upstream,'commit','-m','base')
            subprocess.run(['git','clone',str(upstream),str(fork)],check=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            git(fork,'config','user.name','Test');git(fork,'config','user.email','test@example.invalid')
            (fork/'README.md').write_text('native Arch fork\n')
            (fork/'packaging/base').write_text('native package\n')
            if conflict:(fork/'src/runtime.c').write_text('fork code\n')
            git(fork,'add','.');git(fork,'commit','-m','fork policy')
            before=git(fork,'rev-parse','HEAD').stdout.strip()
            (upstream/'README.md').write_text('new AppImage instructions\n')
            (upstream/'packaging/base').write_text('Windows package\n')
            (upstream/'.github/workflows/windows.yml').write_text('new upstream runner\n')
            (upstream/'src/runtime.c').write_text('fixed upstream code\n')
            git(upstream,'add','.');git(upstream,'commit','-m','upstream fixes')
            result=subprocess.run(['bash',str(ROOT/'packaging/arch/sync-upstream.sh'),str(upstream),'main'],cwd=fork,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual((fork/'README.md').read_text(),'native Arch fork\n')
            self.assertEqual((fork/'packaging/base').read_text(),'native package\n')
            self.assertFalse((fork/'.github/workflows/windows.yml').exists())
            self.assertEqual(git(fork,'status','--porcelain').stdout,'')
            if conflict:
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertEqual(git(fork,'rev-parse','HEAD').stdout.strip(),before)
                self.assertEqual((fork/'src/runtime.c').read_text(),'fork code\n')
            else:
                self.assertEqual(result.returncode,0,result.stdout)
                self.assertEqual((fork/'src/runtime.c').read_text(),'fixed upstream code\n')
                second=subprocess.run(['bash',str(ROOT/'packaging/arch/sync-upstream.sh'),str(upstream),'main'],cwd=fork,capture_output=True,text=True)
                self.assertEqual(second.returncode,0,second.stdout+second.stderr)
                self.assertIn('already synchronized',second.stdout)
