#!/usr/bin/env python3
"""External Kubernetes/Helm recovery; never requires a functioning Argo API."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
K=['kubectl','--context','jshipster','--request-timeout=30s','-n','argocd']

def app(name):
    value=subprocess.check_output(K+['get','application',name,'--ignore-not-found','-o','json'],text=True)
    return json.loads(value) if value.strip() else None

def snapshot(apps):
    return {a['metadata']['name']:{'uid':a['metadata']['uid'],'automated':a['spec'].get('syncPolicy',{}).get('automated')} for a in apps if a}

def patch(name,value):
    subprocess.run(K+['patch','application',name,'--type='+('json' if isinstance(value,list) else 'merge'),'-p',json.dumps(value)],capture_output=True,check=True)

def paused(a):
    if not a:return True
    policy=a['spec'].get('syncPolicy',{}).get('automated')
    return policy is None or policy.get('enabled') is False

def active(a):
    return bool(a and (a.get('operation') or a.get('status',{}).get('operationState',{}).get('phase') in ('Running','Terminating')))

def wait_for_idle():
    deadline=time.monotonic()+120
    while True:
        busy=[]
        for name in ('apps','argocd'):
            current=app(name)
            assert current and paused(current), 'Recovery pause changed; refusing concurrent Helm'
            if active(current):
                busy.append(name)
                if current.get('status',{}).get('operationState',{}).get('phase')=='Running':
                    patch(name,{'status':{'operationState':{'phase':'Terminating'}}})
        if not busy:return
        assert time.monotonic()<deadline, 'Sync did not terminate; leaving reconciliation paused without running Helm'
        time.sleep(2)

def guard():
    if app('argocd'):
        assert all(paused(a) and not active(a) for a in [app(n) for n in ('apps','argocd')]), 'Use argocd_recovery.py recover: pause parent and self-management before Helm'

def restore(state):
    # Restore child before parent so the parent cannot race the saved policy.
    for name in ('argocd','apps'):
        if name not in state:continue
        current=app(name)
        assert current and current['metadata']['uid']==state[name]['uid'], 'Application identity changed; inspect before resuming'
    for name in ('argocd','apps'):
        if name in state:
            saved=state[name]
            change={'op':'replace','path':'/spec/syncPolicy/automated','value':saved['automated']} if saved['automated'] is not None else {'op':'remove','path':'/spec/syncPolicy/automated'}
            patch(name,[{'op':'test','path':'/metadata/uid','value':saved['uid']},change])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['plan','guard','recover','resume'])
    p.add_argument('--state-file',type=Path)
    p.add_argument('--run',action='store_true')
    args=p.parse_args()
    assert os.environ.get('KUBECONFIG'), 'Set an explicit trusted owner KUBECONFIG'
    if args.action=='guard':guard();return
    if args.action=='plan':
        state=snapshot([app(n) for n in ('apps','argocd')])
        print('Recovery will pause:',', '.join(state),'; Helm uses this checkout; resume is separate.')
        subprocess.run(['make','-n','argocd-upgrade'],cwd=ROOT,check=True)
        return
    assert args.run and args.state_file,'Mutations require --run and --state-file'
    if args.action=='resume':
        state=json.loads(args.state_file.read_text());restore(state)
        print('Restored saved automatic reconciliation policies; verify fresh sync and health.')
        return
    state=snapshot([app(n) for n in ('apps','argocd')])
    assert 'apps' in state and 'argocd' in state,'Recovery expects an existing self-managed installation'
    # Fail before touching reconciliation if state cannot be saved exclusively.
    with os.fdopen(os.open(args.state_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:json.dump(state,f)
    for name in ('apps','argocd'):
        patch(name,{'spec':{'syncPolicy':{'automated':{'enabled':False}}}})
        current=app(name)
        if current.get('status',{}).get('operationState',{}).get('phase') in ('Running','Terminating'):
            # Same termination request as Argo's API, sent directly to Kubernetes.
            patch(name,{'status':{'operationState':{'phase':'Terminating'}}})
    wait_for_idle()
    guard()
    print('Parent and self-management paused. Running external Helm recovery.',flush=True)
    subprocess.run(['make','argocd-upgrade'],cwd=ROOT,check=True)
    print('Helm recovery succeeded; reconciliation remains paused. Fix/validate Git desired state, then run resume with this state file.')

if __name__=='__main__':main()
