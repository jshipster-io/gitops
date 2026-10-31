#!/usr/bin/env python3
"""Verify live owner-only OCR admission without creating pods, secrets or RBAC grants."""
import argparse
import json,subprocess
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kubeconfig', required=True)
parser.add_argument('--context', default='jshipster')
args = parser.parse_args()
base=['kubectl','--kubeconfig',args.kubeconfig,'--context',args.context,'-n','azure-operators']

def denied(label,args,reason,body=None):
 p=subprocess.run(base+args,input=json.dumps(body) if body else None,text=True,capture_output=True)
 assert p.returncode and reason in p.stderr, label+' did not receive the expected admission denial'
 print('PASS',label,'denied by isolation policy')
# Impersonation is transient for this negative check; no RBAC grants are created.
denied('Other controller identity', ['--as=system:serviceaccount:argocd:argocd-application-controller','create','token','docintel-operator','--audience=api://AzureADTokenExchange','--duration=10m'], 'Only the named Entra owner')
denied('Owner overlong token',['create','token','docintel-operator','--audience=api://AzureADTokenExchange','--duration=1h'],'ten-minute lifetime')
denied('Owner Kubernetes API audience',['create','token','docintel-operator','--audience=https://kubernetes.default.svc','--duration=10m'],'Azure exchange audience')
# Use dry-run: even an unexpected acceptance cannot start a workload or leave a secret.
pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':'operator-isolation-negative','namespace':'azure-operators'},'spec':{'serviceAccountName':'docintel-operator','automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'runAsUser':1001,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'test','image':'registry.k8s.io/pause:3.10','resources':{'requests':{'cpu':'1m','memory':'8Mi'},'limits':{'cpu':'10m','memory':'16Mi'}},'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}}}]}}
denied('Pod using operator service account',['create','--dry-run=server','-f','-'],'operator namespace cannot run pods',pod)
secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'operator-legacy-token-negative','namespace':'azure-operators','annotations':{'kubernetes.io/service-account.name':'docintel-operator'}},'type':'kubernetes.io/service-account-token'}
denied('Legacy persistent service-account token',['create','--dry-run=server','-f','-'],'operator namespace cannot run pods',secret)
p=subprocess.run(base+['get','pods,secrets','-o','json'],capture_output=True,text=True,check=True)
assert json.loads(p.stdout)['items']==[]
print('PASS operator namespace contains no pods or secrets')
