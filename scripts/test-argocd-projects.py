#!/usr/bin/env python3
import copy
import os
import subprocess
import tempfile
from pathlib import Path
import unittest
import yaml
import argocd_projects as policy
ROOT=Path(__file__).resolve().parents[1]
def project(name):return yaml.safe_load((ROOT/'argo-projects/projects'/f'{name}.yaml').read_text())
def resource(kind,name,namespace=None,group=''):
    d={'apiVersion':group+'/v1' if group else 'v1','kind':kind,'metadata':{'name':name}}
    if namespace:d['metadata']['namespace']=namespace
    return d
class ProjectBoundaryTests(unittest.TestCase):
    def test_owner_sops_workflows_refresh_bindings_only_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'key').touch();(folder/'fixture.yaml').write_text('synthetic fixture')
            (folder/'sops').write_text('#!/bin/sh\nexit "$SOPS_TEST_EXIT"\n')
            (folder/'python3').write_text('#!/bin/sh\ntouch "$BINDING_MARKER"\n')
            for name in ('sops','python3'):(folder/name).chmod(0o700)
            marker=folder/'bound'
            for target in ('sops-encrypt','sops-edit'):
                for status in ('0','42'):
                    marker.unlink(missing_ok=True)
                    env=dict(os.environ,PATH=tmp+os.pathsep+os.environ['PATH'],SOPS_TEST_EXIT=status,BINDING_MARKER=str(marker))
                    result=subprocess.run(['make','-f',str(ROOT/'Makefile'),target,'FILE=fixture.yaml','SOPS_KEY='+str(folder/'key')],cwd=folder,env=env,capture_output=True)
                    self.assertEqual(result.returncode==0,status=='0')
                    self.assertEqual(marker.exists(),status=='0')

    def test_encrypted_identity_binding_survives_payload_only_rotation(self):
        doc={'apiVersion':'ENC[version]','kind':'ENC[kind]','metadata':{'name':'ENC[name]'},'data':{'token':'ENC[value]'}}
        before=policy.identity_hash(doc);doc['data']['token']='ENC[rotated]'
        self.assertEqual(before,policy.identity_hash(doc))
        doc['metadata']['name']='ENC[different-name]'
        self.assertNotEqual(before,policy.identity_hash(doc))

    def test_ordinary_application_positive_and_resource_denials(self):
        p=project('app-hasadnaa')
        self.assertTrue(policy.permits_resource(p,resource('Deployment','hasadnaa','hasadnaa','apps'),'hasadnaa'))
        self.assertTrue(policy.permits_resource(p,resource('Namespace','hasadnaa'),'hasadnaa'))
        for d in [resource('Namespace','argocd'),resource('Deployment','hasadnaa','argocd','apps'),resource('ClusterRole','cluster-admin',group='rbac.authorization.k8s.io'),resource('AppProject','escape','hasadnaa','argoproj.io')]:
            with self.subTest(resource=d):self.assertFalse(policy.permits_resource(p,d,'hasadnaa'))
    def test_sources_and_clusters_are_explicit(self):
        p=project('app-hasadnaa');s={'source':{'repoURL':p['spec']['sourceRepos'][0]},'destination':{'server':policy.SERVER,'namespace':'hasadnaa'}}
        policy.check_application(s,p)
        for field,value in [('repoURL','https://example.invalid/untrusted.git'),('namespace','argocd'),('server','https://other.invalid')]:
            bad=copy.deepcopy(s);bad['source' if field=='repoURL' else 'destination'][field]=value
            with self.subTest(field=field),self.assertRaises(AssertionError):policy.check_application(bad,p)
    def test_worker_names_are_dynamic_but_namespace_and_kinds_are_not(self):
        p=project('app-multi-whatsapp-workers')
        self.assertTrue(policy.permits_resource(p,resource('Deployment','mw-account-new-account','multi-whatsapp','apps'),'multi-whatsapp'))
        for d in [resource('Deployment','mw-account-new','argocd','apps'),resource('Secret','mw-account-new','multi-whatsapp')]:
            self.assertFalse(policy.permits_resource(p,d,'multi-whatsapp'))
    def test_default_deny_and_namespace_only_project(self):
        p=project('default');self.assertEqual(p['spec'],policy.DENY)
        for d in [resource('Namespace','hasadnaa'),resource('Deployment','hasadnaa','hasadnaa','apps')]:self.assertFalse(policy.permits_resource(p,d,'hasadnaa'))
        p=project('platform-pod-security')
        self.assertFalse(policy.permits_resource(p,resource('Secret','sops-age','argocd'),'argocd'))
    def test_control_plane_credentials_and_cross_namespace_exceptions(self):
        self.assertFalse(policy.permits_resource(project('platform-argocd'),resource('Secret','sops-age','argocd'),'argocd'))
        p=project('platform-tailscale')
        identities=yaml.safe_load((ROOT/'argo-projects/resource-identities.yaml').read_text())
        self.assertFalse(policy.permits_identity(identities['tailscale'],resource('Secret','unrelated','kube-system')))
        self.assertFalse(policy.permits_identity(identities['tailscale'],resource('Service','unrelated','kube-system')))
        self.assertFalse(policy.permits_identity(identities['multi-whatsapp-workers'],resource('Deployment','other','multi-whatsapp','apps')))
if __name__=='__main__':unittest.main()
