"""Validate rendered Azure identity bindings without any cloud credentials."""
import pathlib
import uuid
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
FORBIDDEN = {'AZURE_CLIENT_SECRET', 'AZURE_STORAGE_KEY', 'AZURE_STORAGE_ACCOUNT_KEY',
             'AZURE_OPENAI_KEY', 'PG_BACKUP_STORAGE_KEY', 'ACS_CONNECTION_STRING'}


def reject_secret_fields(doc):
    keys = set(doc.get('data', {})) | set(doc.get('stringData', {}))
    forbidden = FORBIDDEN | {'azure-storage-account-key', 'account-key'}
    assert not (keys & forbidden), 'Long-lived Azure credential in active encrypted secret: ' + str(keys & forbidden)


def validate_secret_fields(config):
    for folder in {p['folder'] for p in config['workloads']}:
        path = ROOT / folder
        kustomization = yaml.safe_load((path / 'kustomization.yaml').read_text())
        for generator in kustomization.get('generators', []):
            for filename in yaml.safe_load((path / generator).read_text()).get('files', []):
                for doc in yaml.safe_load_all((path / filename).read_text()):
                    reject_secret_fields(doc)


def validate(docs, config=None):
    config = config or yaml.safe_load((ROOT / 'workload-identity/profiles.yaml').read_text())
    for doc in docs:
        spec = doc.get('spec', {})
        template = spec.get('jobTemplate', {}).get('spec', {}).get('template', {}) if doc['kind'] == 'CronJob' else spec.get('template', {})
        for container in template.get('spec', {}).get('containers', []) + template.get('spec', {}).get('initContainers', []):
            for env in container.get('env', []):
                assert env['name'] not in FORBIDDEN, 'Long-lived Azure credential in rendered workload: ' + env['name']
    objects = {(d['kind'], d['metadata'].get('namespace', 'default'), d['metadata']['name']): d for d in docs}
    for profile in config['workloads']:
        ns, name = profile['namespace'], profile['name']
        identity = str(uuid.UUID(profile['clientID']))
        assert identity == profile['clientID'], 'Invalid identity client ID'
        account = objects.get(('ServiceAccount', ns, profile['serviceAccount']))
        assert account, f'{ns}/{name}: missing service account'
        annotations = account['metadata'].get('annotations', {})
        assert annotations.get('azure.workload.identity/client-id') == identity, f'{ns}/{name}: wrong client ID'
        assert annotations.get('azure.workload.identity/tenant-id') == config['tenantID'], f'{ns}/{name}: wrong tenant'
        workload = objects.get((profile['kind'], ns, name))
        assert workload, f'{ns}/{name}: missing workload'
        spec = workload['spec']
        template = spec['jobTemplate']['spec']['template'] if profile['kind'] == 'CronJob' else spec['template']
        assert template.get('metadata', {}).get('labels', {}).get('azure.workload.identity/use') == 'true', f'{ns}/{name}: missing webhook label'
        assert template['spec'].get('serviceAccountName') == profile['serviceAccount'], f'{ns}/{name}: wrong service account'
        for container in template['spec'].get('containers', []) + template['spec'].get('initContainers', []):
            if profile.get('identity') == 'pg-backups' and 'azure-cli' in container.get('image', ''):
                cli = config['azureCLI']
                envs = {entry['name']: entry.get('value') for entry in container.get('env', [])}
                command = '\n'.join(container.get('command', []) + container.get('args', []))
                assert container['image'] == cli['image'], 'Backup Azure CLI image must match the verified pin'
                assert envs.get('PYTHONPATH') == cli['pythonPath'], 'Use the packaged Azure CLI Python modules'
                assert envs.get('AZURE_STORAGE_AUTH_MODE') == 'login', 'Backup storage must use Azure login'
                assert cli['python'] + ' /var/run/azure-workload-login/login.py' in command, 'Missing verified identity login helper'
                assert '--account-key' not in command, 'Backup cannot use an account-key argument'
            for env in container.get('env', []):
                assert env['name'] not in FORBIDDEN, f'{ns}/{name}: long-lived credential {env["name"]}'
    print(f'Validated {len(config["workloads"])} Azure workload identity bindings')
