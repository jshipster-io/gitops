#!/usr/bin/env python3
"""Fetch immutable public source revisions and apply reviewed dependency patches."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCES = {
    'argo': ('argoproj/argo-cd', 'c2b1e3017e2cec86b122172e861dcd026453ae44'),
    'ksops': ('viaduct-ai/kustomize-sops', 'd9442dc3153d9c16e517a68ce8926c9507386429'),
    'helm': ('helm/helm', 'c0d08d0d6d9424d4a14febb5e8a3e51b0dd00dff'),
    'git-lfs': ('git-lfs/git-lfs', 'a662a6dbfedf706cfa9fc7a5b7bcc7ba2e2c8a65'),
}
for name, (repo, commit) in SOURCES.items():
    dest = ROOT / '.build' / name
    if dest.exists():
        raise SystemExit(f'{dest} exists; use a fresh build checkout')
    dest.mkdir(parents=True)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(dest), *args], text=True).strip()
    git('init', '-q')
    git('remote', 'add', 'origin', f'https://github.com/{repo}.git')
    git('fetch', '--depth=1', 'origin', commit)
    git('checkout', '--detach', 'FETCH_HEAD')
    assert git('rev-parse', 'HEAD') == commit
    git('apply', '--check', str(ROOT / 'patches' / f'{name}.patch'))
    git('apply', str(ROOT / 'patches' / f'{name}.patch'))
    print(f'Prepared {repo}@{commit}')
