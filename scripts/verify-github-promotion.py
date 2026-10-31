#!/usr/bin/env python3
"""Read-only audit of App scopes, grants, CI usage and the production gate.

Requires an authenticated organization owner gh CLI and PyYAML. No secret values
are retrieved. --check-runs also requires successful App mint/use/revoke steps.
"""
import argparse
import base64
import concurrent.futures
import json
from pathlib import Path
import subprocess
import yaml


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def contents(org, repo, path):
    result = api(f'repos/{org}/{repo}/contents/{path}?ref=main')
    return base64.b64decode(result['content']).decode()


def audit_consumer(org, item, config, check_runs):
    repo = item['repo']
    secret_names = {s['name'] for s in api(f'repos/{org}/{repo}/actions/secrets?per_page=100')['secrets']}
    assert 'GITOPS_PAT' not in secret_names, 'legacy repository secret still exists'
    if repo == 'blutag-findmy':
        assert 'FINDMY_APP_PRIVATE_KEY' in secret_names, 'missing dependency App key'
        assert api(f'repos/{org}/{repo}/actions/variables/FINDMY_APP_CLIENT_ID')['value'] == config['dependency']['client_id']
    else:
        assert 'FINDMY_APP_PRIVATE_KEY' not in secret_names, 'unexpected private dependency key grant'
    source = contents(org, repo, item['workflow'])
    assert 'GITOPS_PAT' not in source, 'legacy PAT reference'
    workflow = yaml.safe_load(source)
    writers = []
    readers = []
    for job_id, job in workflow['jobs'].items():
        for step in job.get('steps', []):
            if not step.get('uses', '').startswith('actions/create-github-app-token@'):
                continue
            assert step['uses'].split('@')[1] == config['action']['sha'], 'unexpected token action pin'
            settings = step['with']
            assert settings.get('skip-token-revoke', False) in (False, 'false'), 'token revocation disabled'
            assert settings['owner'] == org, 'wrong App owner'
            condition = job.get('if', '')
            assert "github.ref == 'refs/heads/main'" in condition, 'missing main guard'
            assert "github.event_name != 'pull_request'" in condition, 'missing PR exclusion'
            if settings['repositories'] == 'gitops':
                assert settings['permission-contents'] == 'write'
                assert settings['client-id'] == '${{ vars.GITOPS_APP_CLIENT_ID }}'
                assert settings['private-key'] == '${{ secrets.GITOPS_APP_PRIVATE_KEY }}'
                assert job['permissions'] == {'contents': 'read'}, 'ambient promotion job permissions'
                writers.append(step['name'])
            else:
                assert repo == 'blutag-findmy' and settings['repositories'] == 'FindMy.py'
                assert settings['permission-contents'] == 'read'
                assert settings['client-id'] == '${{ vars.FINDMY_APP_CLIENT_ID }}'
                assert settings['private-key'] == '${{ secrets.FINDMY_APP_PRIVATE_KEY }}'
                readers.append(step['name'])
    assert len(writers) == 1, 'expected exactly one promotion token'
    assert len(readers) == (1 if repo == 'blutag-findmy' else 0)
    detail = 'configuration'
    if check_runs:
        head = api(f'repos/{org}/{repo}/commits/main')['sha']
        runs = api(f'repos/{org}/{repo}/actions/runs?branch=main&head_sha={head}&per_page=100')['workflow_runs']
        # Scheduled quality/evaluation runs can intentionally skip deployment.
        runs = [r for r in runs if r['path'] == item['workflow'] and r['event'] == 'push']
        assert runs, 'no current main push CI run'
        run = max(runs, key=lambda r: r['id'])
        assert run['conclusion'] == 'success', f"CI {run['id']}: {run['status']}/{run['conclusion']}"
        jobs = api(f'repos/{org}/{repo}/actions/runs/{run["id"]}/jobs?per_page=100')['jobs']
        steps = {s['name']: s.get('conclusion') for j in jobs for s in j['steps']}
        for name in writers + readers:
            assert steps.get(name) == 'success', 'token mint step did not succeed'
            assert steps.get('Post ' + name) == 'success', 'token revocation step did not succeed'
        if readers:
            assert steps.get('Verify private dependency access without relying on build cache') == 'success'
        for job in jobs:
            if not any(s['name'] in writers + readers for s in job['steps']):
                continue
            # Capture GitHub's ANSI-formatted log in memory; never render its contents.
            logs = subprocess.check_output(['gh', 'api', '--allow-escape-sequences', f'repos/{org}/{repo}/actions/jobs/{job["id"]}/logs'], text=True)
            assert 'Token revoked' in logs, 'successful revocation not confirmed in job log'
            assert 'Token revocation failed' not in logs, 'token cleanup warning'
        detail = f"CI {run['id']}: mint, promotion and revocation"
    return f'PASS {repo}: {detail}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-runs', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'github-promotion/consumers.json').read_text())
    org = config['organization']
    assert 'GITOPS_PAT' not in {s['name'] for s in api(f'orgs/{org}/actions/secrets?per_page=100')['secrets']}, 'legacy organization secret still exists'
    expected = {x['repo'] for x in config['consumers']}
    installed = {i['app_id']: i for i in api(f'orgs/{org}/installations')['installations']}
    for name in ('promotion', 'dependency'):
        entry = config[name]
        actual = installed[entry['app_id']]
        assert actual['id'] == entry['installation_id']
        assert actual['permissions'] == entry['permissions']
        assert actual['repository_selection'] == 'selected'
        repos = api(f'user/installations/{entry["installation_id"]}/repositories')['repositories']
        assert {r['name'] for r in repos} == set(entry['repositories'])
        print(f'PASS {name} App: exact installation scope and permissions')
    for kind, name in [('secrets', 'GITOPS_APP_PRIVATE_KEY'), ('variables', 'GITOPS_APP_CLIENT_ID')]:
        repos = api(f'orgs/{org}/actions/{kind}/{name}/repositories?per_page=100')['repositories']
        assert {r['name'] for r in repos} == expected, f'{name} grant mismatch'
    assert api(f'orgs/{org}/actions/variables/GITOPS_APP_CLIENT_ID')['value'] == config['promotion']['client_id']
    protection = api(f'repos/{org}/gitops/branches/production/protection')
    assert protection['enforce_admins']['enabled']
    assert not protection['allow_force_pushes']['enabled'] and not protection['allow_deletions']['enabled']
    assert {'context': 'gitops-validation', 'app_id': 15368} in protection['required_status_checks']['checks']
    assert not protection.get('required_pull_request_reviews'), 'unexpected human review gate'
    gate = yaml.safe_load(contents(org, 'gitops', '.github/workflows/gitops-validation.yaml'))
    assert gate['permissions'] == {'contents': 'read'}
    assert 'secrets.' not in json.dumps(gate['jobs']['validate'])
    promote = gate['jobs']['promote']
    assert promote['needs'] == 'validate' and promote['permissions'] == {'contents': 'write'}
    assert promote['if'] == "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'"
    assert 'environment' not in promote and 'secrets.' not in json.dumps(promote)
    print('PASS automatic production gate: mandatory validation, no human approval, built-in token')
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(audit_consumer, org, item, config, args.check_runs): item['repo'] for item in config['consumers']}
        for future in concurrent.futures.as_completed(pending):
            try:
                print(future.result())
            except Exception as error:
                failures.append(pending[future]); print(f'FAIL {pending[future]}: {error}')
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
