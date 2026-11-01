#!/usr/bin/env python3
"""CI runtime check: exact installer image, no credentials, network or capabilities."""
from pathlib import Path
import subprocess
import yaml
values=yaml.safe_load((Path(__file__).resolve().parents[1]/'argocd-ksops-values.yaml').read_text())
init=next(c for c in values['repoServer']['initContainers'] if c['name']=='install-ksops')
subprocess.run(['docker','run','--rm','--network','none','--read-only','--user','65532:65532','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','128m','--cpus','0.2','--tmpfs','/custom-tools:rw,mode=1777,size=64m','--entrypoint',init['command'][0],init['image'],*init['command'][1:]],check=True,timeout=180)
print('PASS exact KSOPS image installs under hardened runtime without credentials')
