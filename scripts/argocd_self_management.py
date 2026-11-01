"""Fail-closed contracts for control-plane adoption and external recovery."""
import yaml
import argocd_bootstrap

def validate(root, docs):
    app=yaml.safe_load((root/'apps/argocd.yaml').read_text())
    assert app['metadata']['name']=='argocd' and app['metadata']['namespace']=='argocd'
    assert not app['metadata'].get('finalizers'), 'Never cascade-delete the control plane'
    assert app['metadata']['annotations']['argocd.argoproj.io/sync-options']=='Prune=false,Delete=false'
    s=app['spec'];assert s['destination']=={'server':'https://kubernetes.default.svc','namespace':'argocd'}
    chart,values=s['sources'];assert len(s['sources'])==2
    assert chart['repoURL']=='https://argoproj.github.io/argo-helm' and chart['chart']=='argo-cd'
    assert chart['targetRevision']==argocd_bootstrap.CHART_VERSION
    assert chart['helm']=={'releaseName':'argocd','valueFiles':['$values/argocd-ksops-values.yaml','$values/argocd/self-management-values.yaml']}
    assert values=={'repoURL':'https://github.com/jshipster-io/gitops.git','targetRevision':'production','ref':'values'}
    assert s['syncPolicy']['automated']==dict(enabled=True,selfHeal=True,prune=True,allowEmpty=False)
    assert set(s['syncPolicy']['syncOptions'])=={'ServerSideApply=true','FailOnSharedResource=true'}
    indexed={(d['kind'],d['metadata']['name']):d for d in docs}
    assert indexed[('ConfigMap','argocd-cm')]['data'].get('application.resourceTrackingMethod','annotation')=='annotation', 'Do not adopt Helm-labeled credentials via label tracking'
    assert not any(d['kind'] in ('Secret','Namespace') for d in docs), 'Credentials and Namespace have separate owners'
    assert not any('helm.sh/hook' in d['metadata'].get('annotations',{}) for d in docs), 'Bootstrap hooks must stay outside routine reconciliation'
    for name in ('argocd-server','argocd-repo-server','argocd-redis','argocd-dex-server','argocd-applicationset-controller','argocd-notifications-controller'):
        assert ('Deployment',name) in indexed, 'Missing essential controller: '+name
    assert ('StatefulSet','argocd-application-controller') in indexed
    for kind,name in [('Deployment','argocd-server'),('Deployment','argocd-repo-server'),('StatefulSet','argocd-application-controller')]:
        containers=indexed[(kind,name)]['spec']['template']['spec']['containers']
        refs=[e['valueFrom']['secretKeyRef'] for c in containers for e in c.get('env',[]) if 'secretKeyRef' in e.get('valueFrom',{})]
        assert any(r.get('name')=='argocd-redis' and r.get('key')=='auth' and r.get('optional') is False for r in refs), 'Redis authentication must remain required'

    for name in ('applications.argoproj.io','applicationsets.argoproj.io','appprojects.argoproj.io'):
        d=indexed[('CustomResourceDefinition',name)]
        assert d['metadata']['annotations']['argocd.argoproj.io/sync-options']=='Prune=false,Delete=false'
    print('PASS Argo self-management ownership, production gate and deletion safeguards')
