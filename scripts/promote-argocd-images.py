#!/usr/bin/env python3
"""Update only the two runtime pins from this build's validated receipts."""
import argparse
import copy
from pathlib import Path
import re
import yaml


def update(text, argocd, ksops, source):
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('Expected an immutable source commit')
    for name, image in [('argocd', argocd), ('ksops', ksops)]:
        if not re.fullmatch(r'prodacr1234\.azurecr\.io/platform-' + name + r'@sha256:[0-9a-f]{64}', image):
            raise ValueError('Invalid candidate receipt for ' + name)
    repository, digest = argocd.split('@')
    tag = source + '@' + digest
    before = yaml.safe_load(text)
    expected = copy.deepcopy(before)
    expected['global']['image'].update(repository=repository, tag=tag)
    installer = [c for c in expected['repoServer']['initContainers'] if c['name'] == 'install-ksops']
    if len(installer) != 1:
        raise ValueError('Expected exactly one KSOPS installer')
    old_ksops = installer[0]['image']
    installer[0]['image'] = ksops
    text, count = re.subn(r'^  image:\n(?:    repository: [^\n]+\n)?    tag: [^\n]+',
                         f'  image:\n    repository: {repository}\n    tag: {tag}', text, flags=re.M)
    if count != 1:
        raise ValueError('Ambiguous global image block')
    text, count = re.subn(r'^      image: ' + re.escape(old_ksops) + r'$',
                         '      image: ' + ksops, text, flags=re.M)
    if count != 1 or yaml.safe_load(text) != expected:
        raise ValueError('Refusing changes outside the two image pins')
    return text


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--values', type=Path, default=Path('argocd-ksops-values.yaml'))
    args = parser.parse_args()
    result = update(args.values.read_text(), (args.receipts/'argocd.txt').read_text().strip(),
                    (args.receipts/'ksops.txt').read_text().strip(), args.source)
    args.values.write_text(result)
