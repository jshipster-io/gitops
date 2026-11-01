"""Credential-free validation for the separately Helm-managed Argo CD bootstrap."""
import os
from pathlib import Path
import subprocess
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART_VERSION = '10.11.6'

def render(root=ROOT):
    assert '--version '+CHART_VERSION in (root/'Makefile').read_text(), 'Helm bootstrap chart pin drift'
    with tempfile.TemporaryDirectory(prefix='argocd-chart-') as tmp:
        env = dict(os.environ, HELM_CACHE_HOME=tmp+'/cache', HELM_CONFIG_HOME=tmp+'/config', HELM_DATA_HOME=tmp+'/data')
        output = subprocess.check_output(['helm','template','argocd','argo-cd','--repo','https://argoproj.github.io/argo-helm','--version',CHART_VERSION,'--namespace','argocd','-f',str(root/'argocd-ksops-values.yaml')], text=True, env=env)
    docs = [d for d in yaml.safe_load_all(output) if d]
    for d in docs:d.setdefault('metadata',{}).setdefault('namespace','argocd')
    return docs

def validate(docs):
    deployment = next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='argocd-repo-server')
    spec = deployment['spec']['template']['spec']
    assert spec['automountServiceAccountToken'] is False, 'Repo-server API token is not needed'
    init = next(c for c in spec['initContainers'] if c['name']=='install-ksops')
    assert '@sha256:' in init['image'], 'Pin KSOPS by digest'
    assert init['command']==['/usr/local/bin/ksops','install','/custom-tools'], 'Preserve bundled Kustomize'
    context=init['securityContext']
    assert context['runAsNonRoot'] is True and context['runAsUser']==65532 and context['runAsGroup']==65532
    assert context['readOnlyRootFilesystem'] is True and context['allowPrivilegeEscalation'] is False
    assert context['capabilities']=={'drop':['ALL']} and context['seccompProfile']=={'type':'RuntimeDefault'}
    assert init['volumeMounts']==[{'mountPath':'/custom-tools','name':'custom-tools'}], 'Installer must not access age keys'
    assert all(init['resources'][side].get(key) for side in ('requests','limits') for key in ('cpu','memory'))
    volumes={v['name']:v for v in spec['volumes']}
    assert volumes['custom-tools']['emptyDir']=={'sizeLimit':'64Mi'}
    main=next(c for c in spec['containers'] if c['name']=='repo-server')
    mount=next(m for m in main['volumeMounts'] if m['name']=='custom-tools')
    assert mount=={'mountPath':'/home/argocd/.config/kustomize/plugin/viaduct.ai/v1/ksops/ksops','name':'custom-tools','subPath':'ksops','readOnly':True}
    assert volumes['sops-age']['secret']['secretName']=='sops-age'
    assert next(m for m in main['volumeMounts'] if m['name']=='sops-age')['readOnly'] is True
    env={e['name']:e.get('value') for e in main['env']}
    assert env['SOPS_AGE_KEY_FILE']=='/.config/sops/age/keys.txt'
    assert env['KUSTOMIZE_PLUGIN_HOME']=='/home/argocd/.config/kustomize/plugin'
    print('PASS hardened KSOPS bootstrap and preserved rendering paths')
