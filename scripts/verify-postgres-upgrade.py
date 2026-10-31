#!/usr/bin/env python3
"""Capture read-only migration evidence or compare two captures.

Capture requires an explicitly selected kubeconfig/context and pod. It never
prints passwords or role verifiers; verifier fingerprints detect accidental
credential changes. Run captures with writers fenced for an exact comparison.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess


def compare(source, target):
    left, right = json.loads(source.read_text()), json.loads(target.read_text())
    # Extension upgrade is the sole intended catalog-data difference.
    for evidence in (left, right):
        for rows in evidence['databases'].values():
            for row in rows:
                if row['kind'] == 'extension' and row['name'] == 'vector':
                    assert row['version'] in ('0.8.6', '0.8.7')
                    row['version'] = 'approved-vector-upgrade'
    if left != right:
        mismatches = []
        for db in sorted(left['databases'].keys() | right['databases'].keys()):
            if left['databases'].get(db) != right['databases'].get(db):
                mismatches.append(db)
        if left['globals'] != right['globals']:
            mismatches.append('roles/memberships/settings')
        raise SystemExit('FAIL: ' + ', '.join(mismatches))
    print(f'PASS: {len(left["databases"])} databases; data, sequences, catalogs and credentials match')


def capture(args):
    command = ['kubectl', '--kubeconfig', args.kubeconfig, '--context', args.context,
               '-n', args.namespace, 'exec', '-i', args.pod, '--', 'psql', '-X',
               '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres']

    def sql(query, db='postgres'):
        result = subprocess.run(command + ['-d', db], input=query, text=True,
                                capture_output=True, check=True)
        return result.stdout.splitlines()

    globals_sql = """
    SELECT json_build_object('role',rolname,'super',rolsuper,'inherit',rolinherit,
      'createrole',rolcreaterole,'createdb',rolcreatedb,'login',rolcanlogin,
      'replication',rolreplication,'bypassrls',rolbypassrls,'limit',rolconnlimit,
      'expires',rolvaliduntil,'password_hash',md5(rolpassword))
    FROM pg_authid WHERE rolname NOT LIKE 'pg_%' ORDER BY rolname;
    SELECT json_build_object('role',pg_get_userbyid(roleid),'member',pg_get_userbyid(member),
      'grantor',pg_get_userbyid(grantor),'admin',admin_option,'inherit',inherit_option,'set',set_option)
    FROM pg_auth_members WHERE pg_get_userbyid(member) NOT LIKE 'pg_%'
    ORDER BY pg_get_userbyid(roleid),pg_get_userbyid(member);
    SELECT json_build_object('database',d.datname,'role',r.rolname,'settings',s.setconfig)
    FROM pg_db_role_setting s LEFT JOIN pg_database d ON d.oid=s.setdatabase
    LEFT JOIN pg_roles r ON r.oid=s.setrole ORDER BY d.datname,r.rolname;
    """
    evidence = {'globals': [json.loads(line) for line in sql(globals_sql)], 'databases': {}}
    inventory = pathlib.Path(__file__).with_name('postgres-inventory.sql').read_text()
    for db in sql('SELECT datname FROM pg_database WHERE datallowconn ORDER BY datname;'):
        evidence['databases'][db] = [json.loads(line) for line in sql(inventory, db)]
        print('Captured:', db, flush=True)
    with args.output.open('x') as out:
        json.dump(evidence, out, indent=2)
    print('Evidence SHA256:', hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    cap = sub.add_parser('capture')
    cap.add_argument('--kubeconfig', required=True)
    cap.add_argument('--context', required=True)
    cap.add_argument('--namespace', default='postgres')
    cap.add_argument('--pod', required=True)
    cap.add_argument('--output', type=pathlib.Path, required=True)
    diff = sub.add_parser('compare')
    diff.add_argument('source', type=pathlib.Path)
    diff.add_argument('target', type=pathlib.Path)
    args = parser.parse_args()
    if args.action == 'capture':
        capture(args)
    else:
        compare(args.source, args.target)
