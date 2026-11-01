#!/usr/bin/env python3
import copy
from pathlib import Path
import tempfile
import unittest
import yaml
import argocd_bootstrap as bootstrap
import argocd_self_management as contract
import argocd_recovery as recovery
from unittest.mock import patch

class SelfManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs=bootstrap.render(self_managed=True)
        cls.app=yaml.safe_load((bootstrap.ROOT/'apps/argocd.yaml').read_text())
    def validate(self,app,docs):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'apps').mkdir();(root/'apps/argocd.yaml').write_text(yaml.safe_dump(app))
            contract.validate(root,docs)
    def test_protected_render(self):self.validate(self.app,self.docs)
    def test_helm_guard_requires_parent_and_child_paused(self):
        def a(name,enabled):return {'metadata':{'name':name,'uid':name},'spec':{'syncPolicy':{'automated':{'enabled':enabled}}}}
        for root,child in [(True,False),(False,True),(True,True)]:
            with patch.object(recovery,'app',side_effect=lambda n:a(n,root if n=='apps' else child)),self.assertRaises(AssertionError):recovery.guard()
        with patch.object(recovery,'app',side_effect=lambda n:a(n,False)):recovery.guard()
        pending=a('argocd',False);pending['operation']={'sync':{}}
        with patch.object(recovery,'app',return_value=pending),self.assertRaises(AssertionError):recovery.guard()
        pending.pop('operation');pending['status']={'operationState':{'phase':'Terminating'}}
        with patch.object(recovery,'app',return_value=pending),self.assertRaises(AssertionError):recovery.guard()
    def test_busy_parent_prevents_child_pause_and_recovery(self):
        with patch.object(recovery,'wait_for_idle',side_effect=RuntimeError('parent busy')) as wait,patch.object(recovery,'patch') as mutate,self.assertRaises(RuntimeError):
            recovery.pause_control_plane()
        wait.assert_called_once_with(('apps',))
        self.assertEqual([x.args[0] for x in mutate.call_args_list],['apps'])

    def test_restore_preserves_policies_and_checks_identity(self):
        state={'apps':{'uid':'root','automated':{'selfHeal':True,'prune':True}},'argocd':{'uid':'child','automated':{'enabled':True,'selfHeal':True,'prune':True}}}
        with patch.object(recovery,'app',side_effect=lambda n:{'metadata':{'uid':state[n]['uid']}}),patch.object(recovery,'patch') as mutate:
            recovery.restore(state)
            self.assertEqual([x.args[0] for x in mutate.call_args_list],['argocd','apps'])
            self.assertEqual(mutate.call_args_list[0].args[1][-1]['value'],state['argocd']['automated'])
            self.assertEqual(mutate.call_args_list[1].args[1][-1],{'op':'replace','path':'/spec/syncPolicy/automated','value':state['apps']['automated']})
        with patch.object(recovery,'app',return_value={'metadata':{'uid':'replacement'}}),patch.object(recovery,'patch') as mutate,self.assertRaises(AssertionError):
            recovery.restore(state)
        mutate.assert_not_called()

    def test_unsafe_ownership_and_delivery_are_rejected(self):
        for change in ('main','manual-gate','cascade','empty','credentials','crd-prune','hook','missing-controller'):
            app=copy.deepcopy(self.app);docs=copy.deepcopy(self.docs)
            if change=='main':app['spec']['sources'][1]['targetRevision']='main'
            elif change=='manual-gate':app['spec']['syncPolicy']['automated']['enabled']=False
            elif change=='cascade':app['metadata']['finalizers']=['resources-finalizer.argocd.argoproj.io']
            elif change=='empty':app['spec']['syncPolicy']['automated']['allowEmpty']=True
            elif change=='credentials':docs.append({'kind':'Secret','metadata':{'name':'sops-age'}})
            elif change=='crd-prune':next(d for d in docs if d['kind']=='CustomResourceDefinition')['metadata']['annotations'].pop('argocd.argoproj.io/sync-options')
            elif change=='hook':docs[0]['metadata'].setdefault('annotations',{})['helm.sh/hook']='pre-upgrade'
            else:docs=[d for d in docs if d['metadata']['name']!='argocd-server']
            with self.subTest(change=change),self.assertRaises((AssertionError,KeyError)):self.validate(app,docs)

if __name__=='__main__':unittest.main()
