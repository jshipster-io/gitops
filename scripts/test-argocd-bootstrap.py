#!/usr/bin/env python3
import copy
import unittest
import argocd_bootstrap

class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.docs=argocd_bootstrap.render()
    def test_render(self):argocd_bootstrap.validate(self.docs)
    def test_privilege_key_exposure_and_plugin_mutation_are_rejected(self):
        for change in ('root','writable','token','key','plugin'):
            docs=copy.deepcopy(self.docs)
            s=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='argocd-repo-server')['spec']['template']['spec']
            i=next(c for c in s['initContainers'] if c['name']=='install-ksops')
            if change=='root':i['securityContext']['runAsUser']=0
            elif change=='writable':i['securityContext']['readOnlyRootFilesystem']=False
            elif change=='token':s['automountServiceAccountToken']=True
            elif change=='key':i['volumeMounts'].append({'name':'sops-age','mountPath':'/keys'})
            else:next(m for m in s['containers'][0]['volumeMounts'] if m['name']=='custom-tools')['readOnly']=False
            with self.subTest(change=change),self.assertRaises(AssertionError):argocd_bootstrap.validate(docs)

if __name__=='__main__':unittest.main()
