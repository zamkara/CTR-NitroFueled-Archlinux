#!/usr/bin/env python3
"""Resolve immutable source inputs; skip a complete release of the same digest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HELPERS=Path(__file__).resolve().parent
ROOT=HELPERS.parents[2]


def identity(policy, upstream):
    if not all(re.fullmatch('[0-9a-f]{40}', value) for value in (policy,upstream)):
        raise ValueError('Expected immutable full source commits')
    return hashlib.sha256((policy+'\n'+upstream+'\n').encode()).hexdigest()[:40]


def complete(release):
    names=[asset['name'] for asset in release.get('assets',[])]
    packages=[name for name in names if re.fullmatch(r'ctr-nitrofueled-.+-x86_64\.pkg\.tar\.zst',name)]
    return not release.get('isDraft') and not release.get('isPrerelease') and len(packages)==1 and {'PKGBUILD','SRCINFO','install.sh','SHA256SUMS','upstream.json'}.issubset(names)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository',default=os.environ.get('GITHUB_REPOSITORY','zamkara/CTR-NitroFueled'))
    p.add_argument('--no-release-check',action='store_true')
    args=p.parse_args()
    config=json.loads((HELPERS/'upstream.json').read_text())
    policy=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    remote=subprocess.check_output(['git','ls-remote','--exit-code',config['repository'],'refs/heads/'+config['branch']],text=True).splitlines()
    if len(remote)!=1: raise ValueError('Expected exactly one upstream branch')
    upstream=remote[0].split()[0]
    digest=identity(policy,upstream)
    tag='arch-'+digest
    required=True
    if not args.no_release_check:
        found=subprocess.run(['gh','release','view',tag,'--repo',args.repository,'--json','isDraft,isPrerelease,assets'],capture_output=True,text=True)
        if found.returncode==0: required=not complete(json.loads(found.stdout))
        elif not any(text in found.stderr.lower() for text in ('release not found','http 404')):
            raise RuntimeError('Cannot verify published release: '+found.stderr)
    values={'commit':policy,'upstream':upstream,'digest':digest,'tag':tag,'build_required':str(required).lower()}
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as file:
            for key,value in values.items(): file.write(f'{key}={value}\n')
    print(json.dumps(values,indent=2))


if __name__=='__main__': main()
