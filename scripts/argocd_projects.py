"""Credential-free, fail-closed checks of Argo project and rendered resource boundaries."""
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import os
import subprocess
import tempfile
import yaml

CLUSTER_KINDS={'Namespace','ClusterRole','ClusterRoleBinding','CustomResourceDefinition','ClusterIssuer','IngressClass','ValidatingAdmissionPolicy','ValidatingAdmissionPolicyBinding','MutatingWebhookConfiguration','ValidatingWebhookConfiguration','Connector','ProxyClass'}
SERVER='https://kubernetes.default.svc'
DENY={'sourceRepos':[],'sourceNamespaces':[],'destinations':[],'clusterResourceWhitelist':[],'namespaceResourceBlacklist':[{'group':'*','kind':'*'}]}

def identity_hash(d):
    identity={k:d.get(k) for k in ('apiVersion','kind')}
    identity['metadata']={k:v for k,v in d['metadata'].items() if k in ('name','namespace')}
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

def matches(rule,group,kind,name):
    return fnmatchcase(group,rule['group']) and fnmatchcase(kind,rule['kind']) and fnmatchcase(name,rule.get('name','*'))

def permits_resource(project,doc,destination):
    s=project['spec'];kind=doc['kind'];meta=doc['metadata'];group=doc['apiVersion'].split('/')[0] if '/' in doc['apiVersion'] else ''
    cluster=kind in CLUSTER_KINDS;scope='cluster' if cluster else 'namespace'
    if not cluster and {'server':SERVER,'namespace':meta.get('namespace',destination)} not in s['destinations']:return False
    allowed=s.get(scope+'ResourceWhitelist',[]);denied=s.get(scope+'ResourceBlacklist',[])
    match=lambda r:matches(r,group,kind,meta.get('name',meta.get('generateName','')))
    return (any(map(match,allowed)) if cluster or allowed else True) and not any(map(match,denied))

def permits_identity(contract,doc,destination=None):
    group=doc['apiVersion'].split('/')[0] if '/' in doc['apiVersion'] else ''
    rules=contract['cluster' if doc['kind'] in CLUSTER_KINDS else 'namespaced']
    return any(matches(r,group,doc['kind'],doc['metadata'].get('name','')) and ('namespace' not in r or r['namespace']==doc['metadata'].get('namespace',destination)) for r in rules)

def check_application(spec,project):
    assert spec['destination'] in project['spec']['destinations'],'Application destination denied'
    for src in spec.get('sources',[spec.get('source',{})]):
        assert src['repoURL'] in project['spec']['sourceRepos'],'Application source denied'

def external_chart(source,namespace):
    """Render an explicitly pinned external chart without credentials or global Helm state."""
    assert source['chart']=='tailscale-operator' and source['repoURL']=='https://pkgs.tailscale.com/helmcharts'
    assert source.get('targetRevision') and not any(x in source['targetRevision'] for x in '*><~^')
    helm=source.get('helm',{})
    assert set(helm)<={'releaseName','valuesObject'},'Unsupported external chart inputs require explicit validation'
    with tempfile.TemporaryDirectory(prefix='project-chart-') as tmp:
        p=Path(tmp);(p/'values.yaml').write_text(yaml.safe_dump(helm.get('valuesObject',{})))
        env=dict(os.environ,HELM_CACHE_HOME=tmp+'/cache',HELM_CONFIG_HOME=tmp+'/config',HELM_DATA_HOME=tmp+'/data')
        raw=subprocess.check_output(['helm','template',helm['releaseName'],source['chart'],'--repo',source['repoURL'],'--version',source['targetRevision'],'--namespace',namespace,'--include-crds','-f',str(p/'values.yaml')],text=True,env=env)
    return [d for d in yaml.safe_load_all(raw) if d]

def validate(root,apps,rendered,workers,managed):
    registry=yaml.safe_load((root/'argo-projects/registry.yaml').read_text());phase=registry['phase']
    assert phase in ('prepare','migrate','enforce')
    projects={d['metadata']['name']:d for d in apps if d['kind']=='AppProject'}
    identities=yaml.safe_load((root/'argo-projects/resource-identities.yaml').read_text())
    expected=registry['applications'];assert len({x['project'] for x in expected.values()})==len(expected),'Project boundaries must be separate'
    assert set(projects)=={x['project'] for x in expected.values()}|({'default'} if phase=='enforce' else set()),'Unexpected project or missing registration'
    for name,p in projects.items():
        assert p['metadata']['namespace']=='argocd'
        assert p['metadata']['annotations']['argocd.argoproj.io/sync-options']=='Prune=false,Delete=false'
        assert not p['metadata'].get('finalizers'),'Projects must survive recovery and parent removal'
        s=p['spec']
        if name=='default':
            assert s==DENY,'Default project must deny all deployment access';continue
        assert s.get('sourceNamespaces')==[] and not s.get('roles') and not s.get('syncWindows'),'No extra ingress, role tokens or manual sync gates'
        assert s['sourceRepos'] and all('*' not in x and '?' not in x for x in s['sourceRepos'])
        assert s['destinations'] and all(x['server']==SERVER and not any(c in x['namespace'] for c in '*?!') for x in s['destinations'])
        assert s.get('namespaceResourceWhitelist') or s.get('namespaceResourceBlacklist')==[{'group':'*','kind':'*'}],'Empty namespace allowlists permit everything in Argo'
        for rule in s['namespaceResourceWhitelist']:
            assert set(rule)=={'group','kind'} and '*' not in rule['group'] and '*' not in rule['kind'],'Explicit namespace resource kinds required'
        for rule in s['clusterResourceWhitelist']:
            assert set(rule)=={'group','kind','name'} and not any(c in str(rule) for c in '*?['),'Explicit cluster resource names required'
    applications=[a for a in apps if a['kind']=='Application']+[yaml.safe_load((root/'apps/apps.yaml').read_text())]
    sets=[a for a in apps if a['kind']=='ApplicationSet'];assert len(sets)==1 and sets[0]['metadata']['name']=='multi-whatsapp-accounts'
    assert sets[0]['spec']['template']['metadata']['name']=='mw-account-{{ .account_id }}'
    applications.append({'metadata':{'name':'multi-whatsapp-workers'},'spec':sets[0]['spec']['template']['spec']})
    assert {a['metadata']['name'] for a in applications}==set(expected),'Every Application and generator needs an explicit project contract'
    for a in applications:
        name=a['metadata']['name'];s=a['spec'];contract=expected[name];p=projects[contract['project']]
        assert s['project'] in ({'default',contract['project']} if phase=='prepare' else {contract['project']}),name+': incorrect project'
        assert s['destination']==contract['destination'],name+': destination contract changed'
        sources=s.get('sources',[s.get('source',{})])
        assert [{k:v for k,v in src.items() if k in ('repoURL','path','chart','ref')} for src in sources]==contract['sources'],name+': source path/identity changed'
        grant=p['spec'];identity=identities[name]
        assert sorted(grant['sourceRepos'])==sorted({src['repoURL'] for src in sources}),'Unused source permission'
        namespaces={s['destination']['namespace']}|{r['namespace'] for r in identity['namespaced']}
        assert sorted(d['namespace'] for d in grant['destinations'])==sorted(namespaces),'Unused namespace permission'
        assert grant['clusterResourceWhitelist']==identity['cluster'],'Cluster permission contract drift'
        assert {(r['group'],r['kind']) for r in grant['namespaceResourceWhitelist']}=={(r['group'],r['kind']) for r in identity['namespaced']},'Namespace permission contract drift'
        if contract['project'].startswith('app-'):
            assert namespaces=={s['destination']['namespace']},'Ordinary apps cannot deploy across namespaces'
            assert not namespaces & {'argocd','kube-system','azure-operators','tailscale','cert-manager','loki','ingress-nginx','pg-backups','postgres','external-dns','default'},'Ordinary apps cannot target infrastructure'
            assert all(r=={'group':'','kind':'Namespace','name':s['destination']['namespace']} for r in identity['cluster']),'Ordinary apps cannot administer cluster resources'
        check_application(s,p)
        docs=[]
        if name=='multi-whatsapp-workers':docs=workers
        elif name=='argocd':docs=managed
        else:
            for src in sources:
                if src.get('chart'):docs+=external_chart(src,s['destination']['namespace'])
                elif src.get('path'):docs+=rendered[src['path']]
        for doc in docs:
            assert permits_identity(identities[name],doc,s['destination']['namespace']),'Unregistered resource identity: '+name+'/'+doc['metadata'].get('name','')
            assert permits_resource(p,doc,s['destination']['namespace']),f"{name}: project denies {doc['kind']}/{doc['metadata'].get('name')}"
    print('PASS 33 Argo project contracts: sources, destinations, cluster names, CI resource identities, hooks and generated workers')
