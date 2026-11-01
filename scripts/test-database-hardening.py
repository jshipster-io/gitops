#!/usr/bin/env python3
import copy
import importlib.util
from pathlib import Path
import unittest
import yaml
import workload_hardening

ROOT=Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
runtime=module('verify-database-runtime');backup=module('verify-backup-runtime')

class DatabaseHardeningTests(unittest.TestCase):
    def test_rehearsal_never_mounts_production_data(self):
        for name in ['statefulset.yaml','statefulset-18.yaml']:
            j=runtime.build_job(name);s=j['spec']['template']['spec']
            self.assertFalse(any('persistentVolumeClaim' in v or 'hostPath' in v for v in s['volumes']))
            self.assertFalse(any('valueFrom' in e for e in s['containers'][0]['env']))
            self.assertIn('listen_addresses=127.0.0.1',s['containers'][0]['args'][0])
            self.assertFalse(s['automountServiceAccountToken'])
            self.assertEqual(s['securityContext']['runAsUser'],999)
    def test_backup_probes_preserve_identity_but_cannot_overwrite_archives(self):
        templates=backup.candidates();self.assertEqual(len(templates),6)
        for source in templates:
            j=backup.build_job(source);s=j['spec']['template']['spec']
            self.assertIn('pg_dump --schema-only ',s['initContainers'][0]['args'][0])
            upload=s['containers'][0]['args'][0]
            self.assertIn('hardening-probes/',upload);self.assertIn('--overwrite false',upload);self.assertIn('trap cleanup EXIT',upload)
            self.assertEqual(s['serviceAccountName'],'pg-backups')
            self.assertFalse(s['automountServiceAccountToken'])
    def test_failed_probe_stops_without_waiting_for_timeout(self):
        from unittest.mock import patch
        import runtime_probe
        with patch.object(runtime_probe.subprocess, 'check_output', return_value='{"status":{"conditions":[{"type":"Failed","status":"True"}]}}'), patch.object(runtime_probe.time, 'sleep') as sleep:
            with self.assertRaises(RuntimeError): runtime_probe.wait_for_completion(['kubectl'], 'synthetic', 10)
            sleep.assert_not_called()

    def test_persistent_volume_contract_guard(self):
        # Use the same validator with a narrow fixture registry, and prove that
        # replica activation, deletion policy and group-ownership drift fail.
        from unittest.mock import patch
        import tempfile
        profile={'namespace':'postgres','kind':'StatefulSet','name':'db','uid':999,'fsGroup':999,'replicas':0,'kubernetesToken':False,'reason':'Retained offline database'}
        d={'kind':'StatefulSet','metadata':{'namespace':'postgres','name':'db'},'spec':{'replicas':0,'persistentVolumeClaimRetentionPolicy':{'whenDeleted':'Retain','whenScaled':'Retain'},'template':{'spec':{'automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'runAsUser':999,'fsGroup':999,'fsGroupChangePolicy':'OnRootMismatch','seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'db','securityContext':{'readOnlyRootFilesystem':True,'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}}]}}}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'pod-security').mkdir();(root/'pod-security/workloads.yaml').write_text(yaml.safe_dump({'workloads':[profile]}))
            with patch.object(workload_hardening,'ROOT',root):
                workload_hardening.validate([d])
                for field in ['replicas','retention','group']:
                    bad=copy.deepcopy(d)
                    if field=='replicas':bad['spec']['replicas']=1
                    if field=='retention':bad['spec']['persistentVolumeClaimRetentionPolicy']['whenDeleted']='Delete'
                    if field=='group':bad['spec']['template']['spec']['securityContext']['fsGroup']=1001
                    with self.subTest(field=field),self.assertRaises(AssertionError):workload_hardening.validate([bad])

if __name__=='__main__':unittest.main()
