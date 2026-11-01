#!/usr/bin/env python3
import copy
import unittest
import argocd_bootstrap

class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.docs=argocd_bootstrap.render()
    def test_render(self):argocd_bootstrap.validate(self.docs)
    def test_privilege_key_exposure_and_plugin_mutation_are_rejected(self):
        for change in ('root','writable','token','key','plugin','argo-image','ksops-image','mixed-argo'):
            docs=copy.deepcopy(self.docs)
            s=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='argocd-repo-server')['spec']['template']['spec']
            i=next(c for c in s['initContainers'] if c['name']=='install-ksops')
            if change=='root':i['securityContext']['runAsUser']=0
            elif change=='writable':i['securityContext']['readOnlyRootFilesystem']=False
            elif change=='token':s['automountServiceAccountToken']=True
            elif change=='key':i['volumeMounts'].append({'name':'sops-age','mountPath':'/keys'})
            elif change=='argo-image':s['containers'][0]['image']='quay.io/argoproj/argocd:latest'
            elif change=='ksops-image':i['image']='prodacr1234.azurecr.io/platform-ksops:latest'
            elif change=='mixed-argo':
                c=next(c for c in s['initContainers'] if c['name']=='copyutil')
                c['image']=c['image'].split('@')[0]+'@sha256:'+'0'*64
            else:next(m for m in s['containers'][0]['volumeMounts'] if m['name']=='custom-tools')['readOnly']=False
            with self.subTest(change=change),self.assertRaises(AssertionError):argocd_bootstrap.validate(docs)

if __name__=='__main__':unittest.main()
