#!/usr/bin/env python3
"""Apply the reviewed native patch queue to a clean, pinned upstream checkout."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess


def run(source, *args):
    return subprocess.run(['git','-C',str(source),*args],check=True,capture_output=True,text=True).stdout.strip()


def apply(source, policy):
    source, policy = Path(source).resolve(), Path(policy).resolve()
    helpers = policy / '.github/workflows/ctr'
    config = json.loads((helpers/'upstream.json').read_text())
    base = config['patch_base']
    if not re.fullmatch('[0-9a-f]{40}',base): raise ValueError('Invalid patch baseline')
    if run(source,'status','--porcelain'): raise ValueError('Source checkout must be clean')
    # Three-way application needs original blobs, including when a caller fetched shallowly.
    exists = subprocess.run(['git','-C',str(source),'cat-file','-e',base+'^{commit}'],capture_output=True).returncode == 0
    if not exists: run(source,'fetch','--no-tags',config['repository'],base)
    original = run(source,'rev-parse','HEAD')
    patches = sorted((helpers/'patches').glob('*.patch'))
    if not patches: raise ValueError('Native feature patch queue is empty')
    try:
        for patch in patches:
            run(source,'apply','--3way','--index',str(patch))
    except subprocess.CalledProcessError as error:
        run(source,'reset','--hard',original)
        raise RuntimeError('Native patches conflict with upstream; review required. '+error.stderr) from error
    # Build-only policy overlay: no upstream workflows or foreign releases are executed.
    shutil.copytree(helpers/'assets',source/'launcher/assets',dirs_exist_ok=True)
    shutil.copytree(helpers/'arch',source/'packaging/arch',dirs_exist_ok=True)
    shutil.copy2(helpers/'test_arch_packaging.py',source/'tests/test_arch_packaging.py')
    shutil.copytree(policy/'.github',source/'.github',dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('.build','__pycache__'))
    for entry in (source/'.github/workflows').glob('*.yml'):
        if entry.name != 'archlinux.yml': entry.unlink()
    for entry in (source/'.github/workflows').glob('*.yaml'): entry.unlink()
    text=(policy/'README.md').read_text().replace('.github/workflows/ctr/docs/','docs/')
    (source/'README.md').write_text(text)
    for name in ('FEATURES.md','CUSA14876.md','UPSTREAM.md'):
        shutil.copy2(helpers/'docs'/name,source/'docs'/name)
    print(f'Applied {len(patches)} native patch file(s) to upstream {original}')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--policy',type=Path,default=Path(__file__).resolve().parents[3])
    args=p.parse_args()
    apply(args.source,args.policy)


if __name__=='__main__': main()
