#!/usr/bin/env python3
"""Owner-only dry-run Argo denial probes; never sync real workloads or grant permissions."""
import argparse,json,os,subprocess,time,uuid
K=['kubectl','--context','jshipster','--request-timeout=30s','-n','argocd']
def run(args,doc=None):
    return subprocess.check_output(K+args,input=json.dumps(doc) if doc else None,text=True)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--default-deny',action='store_true');args=p.parse_args()
    assert args.run and os.environ.get('KUBECONFIG'),'Explicit owner KUBECONFIG and --run required'
    cases=['source','destination','cluster-role','namespace','control-plane-secret']+(['default'] if args.default_deny else [])
    sentinels=[['clusterrole','argo-project-denied-role'],['namespace','argo-project-denied-namespace'],['secret','argo-project-denied-secret']]
    for target in sentinels:assert not run(['get',*target,'--ignore-not-found','-o','name']).strip(),'Probe resource already exists'
    for case in cases:
        name='project-isolation-probe-'+case+'-'+uuid.uuid4().hex[:6]
        source={'repoURL':'https://github.com/jshipster-io/gitops.git','targetRevision':'production','path':'argo-projects/probes/cluster-role'}
        dest={'server':'https://kubernetes.default.svc','namespace':'hasadnaa'}
        if case=='source':source['repoURL']='https://example.invalid/unauthorized.git'
        if case=='destination':dest['namespace']='argocd'
        if case in ('cluster-role','namespace','control-plane-secret'):source['path']='argo-projects/probes/'+case
        doc={'apiVersion':'argoproj.io/v1alpha1','kind':'Application','metadata':{'name':name,'namespace':'argocd'},'spec':{'project':'default' if case=='default' else 'app-hasadnaa','source':source,'destination':dest,'syncPolicy':{'automated':{'enabled':False}}}}
        if case in ('cluster-role','namespace','control-plane-secret'):doc['operation']={'sync':{'dryRun':True,'prune':False},'initiatedBy':{'username':'project-isolation-verifier'}}
        created=json.loads(run(['create','-f','-','-o','json'],doc));uid=created['metadata']['uid']
        try:
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                a=json.loads(run(['get','application',name,'-o','json']));s=a.get('status',{});op=s.get('operationState',{})
                messages=[c.get('message','') for c in s.get('conditions',[])]+[op.get('message','')]+[r.get('message','') for r in op.get('syncResult',{}).get('resources',[])]
                if any('not permitted' in m.lower() or ('do not match any of the allowed destinations' in m.lower() and 'project' in m.lower()) for m in messages):
                    assert not a['metadata'].get('finalizers')
                    if doc.get('operation'):assert (a.get('operation') or op.get('operation',{})).get('sync',{}).get('dryRun') is True
                    print('PASS Argo rejects',case,flush=True);break
                if op.get('phase')=='Succeeded':raise RuntimeError('Dry-run unexpectedly accepted forbidden resource: '+case)
                time.sleep(2)
            else:raise RuntimeError('No project-policy rejection observed: '+case)
        finally:
            current=json.loads(run(['get','application',name,'-o','json']))
            assert current['metadata']['uid']==uid and not current['metadata'].get('finalizers'),'Probe identity changed; do not delete unrelated object'
            run(['delete','application',name,'--wait=true','--timeout=30s'])
    for target in sentinels:assert not run(['get',*target,'--ignore-not-found','-o','name']).strip(),'Dry-run probe unexpectedly created a resource'
    print('PASS denial probes cleaned up; no workload, namespace, Secret or RBAC resources created')
if __name__=='__main__':main()
