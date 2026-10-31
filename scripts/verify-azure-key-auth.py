#!/usr/bin/env python3
"""Read-only Azure authentication audit. Requires owner Azure CLI login; reads no keys."""
import json
import argparse
from pathlib import Path
import subprocess
import urllib.request
import urllib.error

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check-owner-ai', action='store_true', help='Verify operator AI access with one synthetic embedding and metadata reads')
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
config = json.loads((root / "azure-auth/resources.json").read_text())

def az(*args):
    return json.loads(subprocess.check_output(["az", *args, "--subscription", config["subscription"], "-o", "json"]))

for entry in config["resources"]:
    kind, name, group = entry["kind"], entry["name"], entry["group"]
    if kind == "storage":
        state = az("storage", "account", "show", "-g", group, "-n", name)
        assert state.get("allowSharedKeyAccess") is False, name + ": Shared Key is enabled or unspecified"
    elif kind == "cognitive":
        state = az("cognitiveservices", "account", "show", "-g", group, "-n", name)
        assert state["properties"].get("disableLocalAuth") is True, name + ": local auth is enabled"
    else:
        resource = f'/subscriptions/{config["subscription"]}/resourceGroups/{group}/providers/Microsoft.Communication/communicationServices/{name}'
        state = az("rest", "--method", "get", "--url", resource + "?api-version=2025-05-01")
        assert state["properties"].get("disableLocalAuth") is True, name + ": local auth is enabled"
    print("PASS", name, "identity-only authentication setting")

state = az("storage", "blob", "show", "--account-name", "tfstateaks1c9c999c", "--container-name", "tfstate", "--name", "prod-aks.terraform.tfstate", "--auth-mode", "login", "--query", "name")
assert state == "prod-aks.terraform.tfstate"
print("PASS owner Entra read of Terraform state metadata")
if args.check_owner_ai:
    token = az('account', 'get-access-token', '--scope', 'https://cognitiveservices.azure.com/.default')['accessToken']
    speech_id = f'/subscriptions/{config["subscription"]}/resourceGroups/prod-rg/providers/Microsoft.CognitiveServices/accounts/jshipster-speech'
    checks = [
        ('OpenAI', 'https://jshipster-openai.openai.azure.com/openai/deployments/text-embedding-3-small/embeddings?api-version=2024-02-01', token, b'{"input":"synthetic operator identity check"}'),
        ('Document Intelligence v3.1', 'https://jshipster-docintel.cognitiveservices.azure.com/formrecognizer/documentModels?api-version=2023-07-31', token, None),
        ('Speech', 'https://jshipster-speech.cognitiveservices.azure.com/tts/cognitiveservices/voices/list', 'aad#' + speech_id + '#' + token, None),
    ]
    checks.append(('Document Intelligence v4', 'https://jshipster-docintel.cognitiveservices.azure.com/documentintelligence/documentModels?api-version=2024-11-30', token, None))
    failures = []
    for name, url, bearer, body in checks:
        request = urllib.request.Request(url, data=body, headers={'Authorization': 'Bearer ' + bearer, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        if status != 200:
            failures.append(name)
            print('FAIL', name, 'owner Entra request returned HTTP', status)
        else:
            print('PASS', name, 'owner Entra data access')
    if failures:
        raise SystemExit('Operator access incomplete: ' + ', '.join(failures))
print("Settings do not alone prove gateway propagation; verify actual workload operations separately.")
